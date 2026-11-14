"""Single-host durable SQLite job ledger, fenced leases, ownership and receipts.

Exactly-once *commit* is enforced; external provider calls can be re-executed
after process crashes. The DB and files MUST live on a persistent host volume.
"""
from __future__ import annotations
import hashlib
import json
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .contracts import Handoff, ArtifactReceipt, FILE_FORMATS

KEY_RE = re.compile(r"^[A-Za-z0-9_-]{8,96}$")
STAGES = {"planning", "research", "analysis", "rendering", "validating"}
TERMINAL = {"completed", "failed", "cancelled"}


class Conflict(Exception):
    pass


class Missing(Exception):
    pass


class StaleLease(Exception):
    pass


class WorkStore:
    def __init__(self, root: str | Path, upload_scanner=None, object_store=None):
        self.upload_scanner, self.objects = upload_scanner, object_store
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_absolute():
            raise ValueError("Work root must be absolute")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = self.root / "jobs.sqlite3"
        with self._tx() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS jobs(
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, idem TEXT NOT NULL,
              fingerprint TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL,
              stage TEXT NOT NULL, result TEXT NOT NULL DEFAULT '',
              error_code TEXT NOT NULL DEFAULT '', created REAL NOT NULL,
              updated REAL NOT NULL, lease_owner TEXT, lease_until REAL NOT NULL DEFAULT 0,
              fence INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
              cancel_requested INTEGER NOT NULL DEFAULT 0,
              UNIQUE(owner, idem));
            CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status,lease_until,created);
            CREATE TABLE IF NOT EXISTS events(
              seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
              stage TEXT NOT NULL, message TEXT NOT NULL, at REAL NOT NULL,
              FOREIGN KEY(job_id) REFERENCES jobs(id));
            CREATE INDEX IF NOT EXISTS events_job ON events(job_id,seq);
            CREATE TABLE IF NOT EXISTS uploads(
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
              sha256 TEXT NOT NULL, size INTEGER NOT NULL, at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS artifacts(
              id TEXT PRIMARY KEY, job_id TEXT NOT NULL, kind TEXT NOT NULL,
              name TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
              at REAL NOT NULL, UNIQUE(job_id,kind),
              FOREIGN KEY(job_id) REFERENCES jobs(id));
            CREATE TABLE IF NOT EXISTS proposals(
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, job_id TEXT NOT NULL,
              cadence_minutes INTEGER NOT NULL, status TEXT NOT NULL,
              at REAL NOT NULL, next_run REAL NOT NULL DEFAULT 0,
              runs INTEGER NOT NULL DEFAULT 0, max_runs INTEGER NOT NULL DEFAULT 10,
              FOREIGN KEY(job_id) REFERENCES jobs(id));
            CREATE TABLE IF NOT EXISTS agent_steps(
              job_id TEXT NOT NULL, agent TEXT NOT NULL,
              status TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
              started REAL NOT NULL DEFAULT 0, finished REAL NOT NULL DEFAULT 0,
              deadline REAL NOT NULL DEFAULT 0, updated REAL NOT NULL DEFAULT 0,
              result_json TEXT NOT NULL DEFAULT '', result_sha256 TEXT NOT NULL DEFAULT '',
              error_code TEXT NOT NULL DEFAULT '', qa_json TEXT NOT NULL DEFAULT '',
              PRIMARY KEY(job_id,agent),
              FOREIGN KEY(job_id) REFERENCES jobs(id));
            CREATE INDEX IF NOT EXISTS agent_steps_status ON agent_steps(status,updated);
            CREATE TABLE IF NOT EXISTS job_plans(
              job_id TEXT PRIMARY KEY, plan_json TEXT NOT NULL, sha256 TEXT NOT NULL,
              created REAL NOT NULL, FOREIGN KEY(job_id) REFERENCES jobs(id));
            CREATE TABLE IF NOT EXISTS job_lineage(
              child_id TEXT PRIMARY KEY, parent_id TEXT NOT NULL,
              operation TEXT NOT NULL, created REAL NOT NULL,
              FOREIGN KEY(child_id) REFERENCES jobs(id),
              FOREIGN KEY(parent_id) REFERENCES jobs(id));
            CREATE INDEX IF NOT EXISTS lineage_parent ON job_lineage(parent_id);
            CREATE TABLE IF NOT EXISTS agent_approvals(
              id TEXT PRIMARY KEY, owner TEXT NOT NULL,
              action TEXT NOT NULL, arguments TEXT NOT NULL,
              status TEXT NOT NULL, created REAL NOT NULL,
              expires REAL NOT NULL, result TEXT NOT NULL DEFAULT '');
            CREATE INDEX IF NOT EXISTS agent_approvals_owner
              ON agent_approvals(owner,status,expires);
            """)

    @contextmanager
    def _tx(self):
        con = sqlite3.connect(self.db, timeout=15, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=15000")
        con.execute("PRAGMA journal_mode=WAL")
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    @staticmethod
    def _event(c, jid, stage, message):
        c.execute("INSERT INTO events(job_id,stage,message,at) VALUES(?,?,?,?)",
                  (jid, stage, message[:180], time.time()))

    def submit(self, owner: str, objective: str, formats: list[str],
               idem: str, uploads: list[str] | None = None,
               source_ids: list[str] | None = None,
               source_coverage: str = "targeted") -> dict:
        if not isinstance(idem, str) or not KEY_RE.fullmatch(idem):
            raise ValueError("Idempotency-Key must be 8-96 safe characters")
        if not isinstance(formats, list) or not all(isinstance(f, str) for f in formats):
            raise ValueError("Invalid deliverables")
        Handoff(session_id=owner, objective=objective,
                deliverables=tuple(formats)).validate()
        if not isinstance(uploads, list) or len(uploads) > 4 or len(set(uploads)) != len(uploads):
            raise ValueError("Invalid upload references")
        source_ids=source_ids or []
        if (not isinstance(source_ids,list) or len(source_ids)>8 or
            any(type(uid) is not str for uid in source_ids) or
            len(set(source_ids))!=len(source_ids) or
            source_coverage not in ("targeted","complete")):
            raise ValueError("Invalid source scope")
        if source_ids:
            from .source_index import SourceIndex
            owned={x["id"] for x in SourceIndex(self.root).list(owner)}
            if not set(source_ids).issubset(owned):
                raise Missing("Selected Work source is unavailable")
        payload = {"objective": objective, "deliverables": formats, "uploads": uploads,
                   "source_ids": source_ids, "source_coverage": source_coverage}
        # New agentic submissions do not select specialists until the worker
        # obtains an authenticated job lease and requests a model-authored plan.
        import os
        agentic=os.environ.get("RIZZLER_AGENTIC_ENABLED",
            "1" if os.environ.get("RIZZLER_DEPLOYMENT_MODE")=="production" else "0"
            ).strip().lower() in ("1","true","yes")
        if agentic:
            from .work_dynamic import pending
            planned=[]
            graph=pending()
        else:
            # Historic jobs remain readable/runnable during migration only.
            from .work_agents import plan
            planned=plan(payload)
            from .task_planning import execution_graph
            graph=execution_graph(payload)
        plan_json = json.dumps(graph, sort_keys=True, separators=(",", ":"))
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        jid, t = secrets.token_hex(16), time.time()
        with self._tx() as c:
            existing = c.execute("SELECT * FROM jobs WHERE owner=? AND idem=?",
                                 (owner, idem)).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise Conflict("Idempotency key belongs to another request")
                return self._view(existing)
            active=c.execute("""SELECT count(*) FROM jobs WHERE owner=?
                AND status IN ('queued','running')""",(owner,)).fetchone()[0]
            if active >= 20:
                raise Conflict("Too many active jobs")
            if uploads:
                q = ",".join("?" * len(uploads))
                n = c.execute(f"SELECT count(*) FROM uploads WHERE owner=? AND id IN ({q})",
                              [owner, *uploads]).fetchone()[0]
                if n != len(uploads):
                    raise Missing("Upload not found")
            c.execute("""INSERT INTO jobs(id,owner,idem,fingerprint,payload,status,stage,created,updated)
                         VALUES(?,?,?,?,?,'queued','accepted',?,?)""",
                      (jid, owner, idem, fingerprint, canonical, t, t))
            for spec in planned:
                c.execute("""INSERT INTO agent_steps(job_id,agent,status,updated)
                             VALUES(?,?,'queued',?)""", (jid,spec.name,t))
            c.execute("""INSERT INTO job_plans(job_id,plan_json,sha256,created)
                         VALUES(?,?,?,?)""",
                      (jid,plan_json,hashlib.sha256(plan_json.encode()).hexdigest(),t))
            self._event(c, jid, "queued", "Accepted and queued")
            return self._view(c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone())

    @staticmethod
    def _view(row):
        return {key: row[key] for key in (
            "id", "status", "stage", "result", "error_code", "created", "updated",
            "attempts", "cancel_requested")}

    def get(self, owner: str, jid: str):
        with self._tx() as c:
            row = c.execute("SELECT * FROM jobs WHERE owner=? AND id=?", (owner, jid)).fetchone()
            if row is None:
                raise Missing("Job not found")
            return self._view(row)

    def list_jobs(self, owner: str):
        with self._tx() as c:
            return [self._view(row) for row in c.execute(
                "SELECT * FROM jobs WHERE owner=? ORDER BY created DESC LIMIT 50", (owner,))]

    def job_plan(self, owner: str, jid: str) -> dict:
        """Owner-scoped, checksum-protected immutable execution plan."""
        with self._tx() as c:
            row = c.execute("SELECT payload FROM jobs WHERE id=? AND owner=?",
                            (jid, owner)).fetchone()
            if row is None:
                raise Missing("Job not found")
            payload = json.loads(row["payload"])
            saved = c.execute("SELECT plan_json,sha256 FROM job_plans WHERE job_id=?",
                              (jid,)).fetchone()
            if saved is None:
                raise ValueError("Job has no persisted plan")
            raw = saved["plan_json"]
            if hashlib.sha256(raw.encode()).hexdigest() != saved["sha256"]:
                raise ValueError("Job execution plan failed integrity verification")
            result = json.loads(raw)
            if result.get("schema_version") == 2:
                from .work_dynamic import validate
                return validate(result,payload)
            # Old plans are immutable; no dynamic job can silently fall back.
            from .task_planning import execution_graph, validate_graph
            expected=execution_graph(payload)
            validate_graph(result, frozenset(x["id"] for x in expected["steps"]))
            if result != expected:
                raise ValueError("Legacy graph differs from approved workflow")
            return result

    def install_dynamic_graph(self, owner: str, jid: str, worker: str,
                              fence: int, proposed: dict) -> dict:
        """Fenced, atomic publication of a model-generated plan.

        Never replace a committed plan after restart. Existing checkpoints
        always refer to the same plan checksum.
        """
        from .work_dynamic import validate
        with self._tx() as c:
            row=self._active(c,jid,worker,fence)
            if row["owner"]!=owner:raise Missing("Job owner mismatch")
            payload=json.loads(row["payload"])
            validated=validate(proposed,payload)
            if validated["status"]!="ready":raise ValueError("Model plan not executable")
            saved=c.execute("SELECT plan_json,sha256 FROM job_plans WHERE job_id=?",
                            (jid,)).fetchone()
            if saved is None:raise ValueError("Missing planning placeholder")
            if hashlib.sha256(saved["plan_json"].encode()).hexdigest()!=saved["sha256"]:
                raise ValueError("Corrupted plan checkpoint")
            previous=json.loads(saved["plan_json"])
            if previous.get("schema_version")!=2:
                raise ValueError("Legacy plan cannot be overwritten")
            if previous["status"]=="ready":
                if previous!=validated:
                    raise Conflict("A different Work graph was already committed")
                return previous
            encoded=json.dumps(validated,sort_keys=True,separators=(",",":"))
            stamp=time.time()
            c.execute("UPDATE job_plans SET plan_json=?,sha256=?,created=? WHERE job_id=?",
                      (encoded,hashlib.sha256(encoded.encode()).hexdigest(),stamp,jid))
            for node in validated["steps"]:
                c.execute("""INSERT INTO agent_steps(job_id,agent,status,updated)
                             VALUES(?,?,'queued',?)""",(jid,node["id"],stamp))
            self._event(c,jid,"planning","Model-authored execution graph committed")
            return validated

    def specification(self, owner: str, jid: str) -> dict:
        """Return the authenticated owner's original objective and output contract."""
        with self._tx() as c:
            row=c.execute("SELECT payload FROM jobs WHERE owner=? AND id=?",
                          (owner,jid)).fetchone()
            if row is None:
                raise Missing("Job not found")
            return json.loads(row["payload"])

    def lineage(self, owner: str, jid: str) -> dict:
        """Owner-scoped original/revision/retry relationships; never reveal other users."""
        self.get(owner,jid)
        with self._tx() as c:
            parents=[dict(r) for r in c.execute(
                """SELECT l.parent_id,l.operation,l.created FROM job_lineage l
                   JOIN jobs j ON j.id=l.parent_id
                   WHERE l.child_id=? AND j.owner=?""",(jid,owner))]
            children=[dict(r) for r in c.execute(
                """SELECT l.child_id,l.operation,l.created FROM job_lineage l
                   JOIN jobs j ON j.id=l.child_id
                   WHERE l.parent_id=? AND j.owner=?
                   ORDER BY l.created DESC LIMIT 50""",(jid,owner))]
        return {"parents":parents,"children":children}

    def derive(self, owner: str, jid: str, objective: str | None,
               formats: list[str] | None, idem: str, operation: str = "revise") -> dict:
        """Create a new version, preserving the original job and immutable audit trail.

        A running job is not silently modified. Clients must cancel it separately
        when genuinely requested. The new version owns independent QA/receipts.
        """
        if operation not in ("revise","retry"):
            raise ValueError("Invalid job revision operation")
        original=self.get(owner,jid)
        source=self.specification(owner,jid)
        if operation == "retry":
            if original["status"] not in ("failed","cancelled"):
                raise Conflict("Only terminal unsuccessful jobs may be retried")
            if objective is not None or formats is not None:
                raise ValueError("Retry does not accept changed scope")
            objective,formats=source["objective"],source["deliverables"]
        else:
            if not isinstance(objective,str) or not isinstance(formats,list):
                raise ValueError("Revision requires a new objective and deliverables")
        new=self.submit(owner,objective,formats,idem,source["uploads"],
                        source.get("source_ids",[]),source.get("source_coverage","targeted"))
        if new["id"] == jid:
            raise Conflict("Cannot derive a job from itself")
        with self._tx() as c:
            row=c.execute("SELECT parent_id,operation FROM job_lineage WHERE child_id=?",
                          (new["id"],)).fetchone()
            if row and (row["parent_id"] != jid or row["operation"] != operation):
                raise Conflict("Idempotency key belongs to a different derivation")
            if not row:
                c.execute("""INSERT INTO job_lineage(child_id,parent_id,operation,created)
                             VALUES(?,?,?,?)""",(new["id"],jid,operation,time.time()))
                self._event(c,new["id"],"queued","Created from owned "+operation+" job")
        return new

    def prepare_agent_action(self, owner: str, action: str, arguments: dict) -> dict:
        """Prepare but never execute a model-proposed mutation."""
        if action not in ("work.cancel", "work.revise", "work.retry"):
            raise PermissionError("Unsupported action")
        if not isinstance(arguments, dict) or not isinstance(arguments.get("job_id"), str):
            raise ValueError("Missing owned job")
        jid=arguments["job_id"]
        self.get(owner, jid)
        if action == "work.revise":
            from .contracts import Handoff
            Handoff(session_id=owner,objective=arguments.get("objective",""),
                    deliverables=tuple(arguments.get("deliverables",[]))).validate()
        if action == "work.retry" and self.get(owner,jid)["status"] not in ("failed","cancelled"):
            raise Conflict("Only failed or cancelled work can be retried")
        if action != "work.revise" and set(arguments)!={"job_id"}:
            raise ValueError("Unexpected mutation arguments")
        if action == "work.revise" and set(arguments)!={"job_id","objective","deliverables"}:
            raise ValueError("Invalid revision arguments")
        now=time.time()
        key=secrets.token_hex(16)
        with self._tx() as c:
            c.execute("DELETE FROM agent_approvals WHERE expires<? AND status='pending'",(now,))
            count=c.execute("SELECT COUNT(*) FROM agent_approvals WHERE owner=? AND status='pending'",
                            (owner,)).fetchone()[0]
            if count>=16:raise Conflict("Too many unconfirmed actions")
            c.execute("""INSERT INTO agent_approvals(id,owner,action,arguments,status,created,expires)
                         VALUES(?,?,?,?,'pending',?,?)""",
                      (key,owner,action,json.dumps(arguments,sort_keys=True),now,now+600))
        return {"id":key,"action":action,"job_id":jid,
                "objective":arguments.get("objective"),
                "deliverables":arguments.get("deliverables"),
                "expires_at":now+600}

    def confirm_agent_action(self, owner: str, approval_id: str) -> dict:
        """Separate authenticated confirmation; crash-safe retry via action idempotency."""
        if not isinstance(approval_id,str) or not re.fullmatch(r"[a-f0-9]{32}",approval_id):
            raise ValueError("Invalid action identifier")
        with self._tx() as c:
            row=c.execute("SELECT * FROM agent_approvals WHERE id=? AND owner=?",
                          (approval_id,owner)).fetchone()
            if row is None:raise Missing("Action confirmation not found")
            if row["status"]=="completed":
                return json.loads(row["result"])
            if row["status"]=="pending":
                if row["expires"]<time.time():
                    raise Conflict("Action approval expired")
                c.execute("UPDATE agent_approvals SET status='executing' WHERE id=?",
                          (approval_id,))
            elif row["status"]!="executing":
                raise Conflict("Action unavailable")
            action,params=row["action"],json.loads(row["arguments"])
        # On process crash, a repeated explicit confirmation finishes the same
        # action. Revision and retry reuse the approval ID as idempotency key.
        if action=="work.cancel":
            result=self.cancel(owner,params["job_id"])
        elif action=="work.retry":
            result=self.derive(owner,params["job_id"],None,None,
                               "agent_"+approval_id,"retry")
        elif action=="work.revise":
            result=self.derive(owner,params["job_id"],params["objective"],
                               params["deliverables"],"agent_"+approval_id,"revise")
        else:
            raise PermissionError("Unknown saved action")
        with self._tx() as c:
            c.execute("""UPDATE agent_approvals SET status='completed',result=?
                         WHERE id=? AND owner=?""",(json.dumps(result),approval_id,owner))
        return result

    def events(self, owner: str, jid: str, after: int = 0):
        self.get(owner, jid)
        with self._tx() as c:
            return [dict(x) for x in c.execute(
                "SELECT seq,stage,message,at FROM events WHERE job_id=? AND seq>? ORDER BY seq LIMIT 200",
                (jid, after))]

    def cancel(self, owner: str, jid: str):
        with self._tx() as c:
            row = c.execute("SELECT * FROM jobs WHERE owner=? AND id=?", (owner, jid)).fetchone()
            if row is None:
                raise Missing("Job not found")
            if row["status"] == "queued":
                c.execute("UPDATE jobs SET status='cancelled',stage='cancelled',updated=? WHERE id=?",
                          (time.time(), jid))
                self._settle_agents(c, jid, "cancelled")
                self._event(c, jid, "cancelled", "Cancelled before execution")
            elif row["status"] == "running":
                c.execute("UPDATE jobs SET cancel_requested=1,updated=? WHERE id=?",
                          (time.time(), jid))
                self._event(c, jid, "cancelling", "Cancellation requested")
            return self._view(c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone())

    def claim(self, worker: str, lease_seconds: float = 30):
        """Reap expired or cancelled tasks without starving later queued work."""
        if not isinstance(worker, str) or not worker or not 5 <= lease_seconds <= 600:
            raise ValueError("Invalid worker or lease")
        with self._tx() as c:
            return self._claim_locked(c,worker,lease_seconds,time.time())

    def _claim_locked(self,c,worker,lease_seconds,now):
        """The scheduler invokes this only within an atomic claim transaction."""
        while True:
            row = c.execute("""SELECT j.* FROM jobs j WHERE
                (j.status='queued' OR (j.status='running' AND j.lease_until < ?))
                AND NOT EXISTS (
                    SELECT 1 FROM jobs active
                    WHERE active.owner=j.owner AND active.id<>j.id
                      AND active.status='running' AND active.lease_until>=?
                )
                ORDER BY j.created LIMIT 1""",(now,now)).fetchone()
            if row is None:
                return None
            jid = row["id"]
            if row["cancel_requested"]:
                c.execute("""UPDATE jobs SET status='cancelled',stage='cancelled',
                             lease_owner=NULL,lease_until=0,updated=? WHERE id=?""", (now, jid))
                self._settle_agents(c, jid, "cancelled")
                self._event(c, jid, "cancelled", "Cancelled during recovery")
                continue
            if row["attempts"] >= 3:
                c.execute("""UPDATE jobs SET status='failed',stage='failed',
                    error_code='max_attempts',lease_owner=NULL,lease_until=0,updated=? WHERE id=?""",
                          (now, jid))
                self._settle_agents(c, jid, "failed")
                self._event(c, jid, "failed", "Execution retries exhausted")
                continue
            fence = row["fence"] + 1
            c.execute("""UPDATE jobs SET status='running',stage='planning',
                  lease_owner=?,lease_until=?,fence=?,attempts=attempts+1,updated=?
                  WHERE id=?""", (worker, now+lease_seconds, fence, now, jid))
            self._event(c, jid, "running", "Worker leased task")
            return {"id": jid, "owner": row["owner"], "fence": fence,
                    "payload": json.loads(row["payload"])}

    def _active(self, c, jid, worker, fence):
        row = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        if not row or row["status"]!="running" or row["lease_owner"]!=worker or row["fence"]!=fence or row["lease_until"]<=time.time():
            raise StaleLease("Worker no longer owns task")
        if row["cancel_requested"]:
            raise InterruptedError("Task cancelled")
        return row

    def renew(self, jid, worker, fence, stage=None, lease_seconds=30):
        with self._tx() as c:
            row = self._active(c,jid,worker,fence)
            if stage is not None and stage not in STAGES:
                raise ValueError("Invalid stage")
            now = time.time()
            c.execute("UPDATE jobs SET lease_until=?,stage=?,updated=? WHERE id=?",
                      (now+lease_seconds,stage or row["stage"],now,jid))
            if stage is not None and stage != row["stage"]:
                self._event(c,jid,stage,"Stage started")

    def finish(self, jid, worker, fence, result, receipts: list[ArtifactReceipt], storage: Path):
        from .contracts import completion_gate
        with self._tx() as c:
            row = self._active(c,jid,worker,fence)
            h = json.loads(row["payload"])
            handoff = Handoff(session_id=row["owner"],objective=h["objective"],
                              deliverables=tuple(h["deliverables"]))
            completion_gate(handoff, receipts, "completed")
            if not isinstance(result,str) or not result.strip():
                raise ValueError("No substantive result")
            # Publish into the owned durable directory only after validating the
            # current lease, inside the exclusive DB transaction. Crash-before-
            # commit files remain unindexed; retries may safely replace them.
            target = self.root / "artifacts" / row["owner"] / jid
            target.mkdir(parents=True, exist_ok=True, mode=0o700)
            for receipt in receipts:
                p = storage / (receipt.kind + "." + receipt.kind)
                if not p.is_file() or p.stat().st_size != receipt.byte_size or hashlib.sha256(p.read_bytes()).hexdigest()!=receipt.sha256:
                    raise ValueError("Artifact bytes do not match receipt")
                import shutil
                temp = target / (receipt.name + "." + secrets.token_hex(8) + ".tmp")
                shutil.copyfile(p, temp)
                if hashlib.sha256(temp.read_bytes()).hexdigest()!=receipt.sha256:
                    temp.unlink(missing_ok=True)
                    raise ValueError("Artifact publish checksum mismatch")
                temp.replace(target / receipt.name)
                if self.objects is not None:
                    self.objects.put(f"artifacts/{row['owner']}/{jid}/{receipt.name}",
                                     target / receipt.name, receipt.sha256, receipt.byte_size)
                c.execute("""INSERT INTO artifacts(id,job_id,kind,name,sha256,size,at)
                             VALUES(?,?,?,?,?,?,?)""",(
                    secrets.token_hex(16), jid, receipt.kind, p.name, receipt.sha256,
                    receipt.byte_size,time.time()))
            c.execute("""UPDATE jobs SET status='completed',stage='completed',
                result=?,lease_owner=NULL,lease_until=0,updated=? WHERE id=?""",
                (result[:10000],time.time(),jid))
            # An automation plan creates a *pending* proposal only after verified
            # completion. Scheduled repetitions must never create new schedules.
            if "automation_plan" in h["deliverables"] and not row["idem"].startswith("schedule_"):
                c.execute("""INSERT INTO proposals(
                    id,owner,job_id,cadence_minutes,status,at,max_runs)
                    VALUES(?,?,?,1440,'pending_approval',?,10)""",
                    (secrets.token_hex(16),row["owner"],jid,time.time()))
                self._event(c,jid,"automation_plan","Draft schedule pending owner approval")
            self._event(c,jid,"completed","All required outputs verified")

    def agent_steps(self, owner: str, jid: str) -> list[dict]:
        """Owner-scoped durable per-agent statuses and SLA evidence."""
        with self._tx() as c:
            if c.execute("SELECT id FROM jobs WHERE id=? AND owner=?", (jid, owner)).fetchone() is None:
                raise Missing("Job not found")
            return [dict(row) for row in c.execute(
                """SELECT agent,status,attempt,started,finished,deadline,updated,
                          error_code,result_sha256,qa_json FROM agent_steps
                   WHERE job_id=? ORDER BY started,agent""", (jid,))]

    def quality_report(self, owner: str, jid: str) -> dict:
        """Only announce final quality after the parent job commits successfully."""
        with self._tx() as c:
            parent = c.execute("SELECT status FROM jobs WHERE id=? AND owner=?",
                               (jid,owner)).fetchone()
            if parent is None:
                raise Missing("Job not found")
            if parent["status"] != "completed":
                return {"job_id": jid, "status": parent["status"], "quality": None}
            row = c.execute("""SELECT status,result_json,result_sha256 FROM agent_steps
                               WHERE job_id=? AND agent='quality'""", (jid,)).fetchone()
            if not row or row["status"] != "completed":
                return {"job_id": jid, "status": "not_completed", "quality": None}
            raw = row["result_json"]
            if hashlib.sha256(raw.encode()).hexdigest() != row["result_sha256"]:
                raise ValueError("Persisted quality verdict corrupted")
            data = json.loads(raw)
            if data.get("passed") is not True:
                raise ValueError("Invalid persisted quality result")
            return {"job_id": jid, "status": "completed", "quality": data}

    def agent_publish(self, jid: str, worker: str, fence: int, owner: str,
                      source: Path, receipt: ArtifactReceipt) -> Path:
        """Fence the final promotion of a staged file into the shared checkpoint.

        Rendering happens in a per-fence attempt directory; timed-out native
        threads can never write into a newer worker's committed artifact.
        """
        receipt.validate()
        if receipt.name != receipt.kind + "." + receipt.kind:
            raise ValueError("Unexpected specialist artifact name")
        source = Path(source)
        root = self.root / "attempts" / owner / jid / str(fence)
        root = root.resolve()
        candidate = source.resolve()
        if root not in candidate.parents or source.is_symlink() or not source.is_file():
            raise ValueError("Invalid isolated artifact staging path")
        if (source.stat().st_size != receipt.byte_size or
                hashlib.sha256(source.read_bytes()).hexdigest() != receipt.sha256):
            raise ValueError("Specialist staging checksum mismatch")
        with self._tx() as c:
            row = self._active(c, jid, worker, fence)
            if row["owner"] != owner:
                raise Missing("Wrong artifact owner")
            destination = self.root / "checkpoints" / owner / jid / receipt.name
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if destination.is_symlink():
                raise ValueError("Unsafe checkpoint link")
            source.replace(destination)
            return destination

    def agent_checkpoint(self, jid: str, worker: str, fence: int, agent: str):
        """A committed step is reusable only while the caller owns the parent lease."""
        from .work_agents import SPECS
        if agent not in SPECS:
            raise ValueError("Unknown specialist")
        with self._tx() as c:
            self._active(c, jid, worker, fence)
            record = c.execute("SELECT * FROM agent_steps WHERE job_id=? AND agent=?",
                               (jid, agent)).fetchone()
            if record and record["status"] == "completed":
                raw = record["result_json"]
                if hashlib.sha256(raw.encode()).hexdigest() != record["result_sha256"]:
                    raise ValueError("Persistent agent checkpoint corrupted")
                return json.loads(raw)
            return None

    def agent_begin(self, jid: str, worker: str, fence: int, agent: str, target_seconds: int):
        """Agent transitions share the job's fenced transactional ownership."""
        from .work_agents import SPECS
        if agent not in SPECS or not 5 <= target_seconds <= 3600:
            raise ValueError("Invalid agent or SLA budget")
        now = time.time()
        with self._tx() as c:
            self._active(c, jid, worker, fence)
            existing = c.execute("SELECT status FROM agent_steps WHERE job_id=? AND agent=?",
                                 (jid, agent)).fetchone()
            if existing and existing["status"] == "completed":
                raise ValueError("Committed agent step cannot be restarted")
            c.execute("""INSERT INTO agent_steps(job_id,agent,status,attempt,started,
                       deadline,updated) VALUES(?,?,'running',1,?,?,?)
                       ON CONFLICT(job_id,agent) DO UPDATE SET
                       status='running',attempt=agent_steps.attempt+1,
                       started=excluded.started,deadline=excluded.deadline,
                       updated=excluded.updated,error_code='',qa_json='',
                       result_json='',result_sha256='',finished=0""",
                      (jid,agent,now,now+target_seconds,now))
            self._event(c,jid,"agent_started",agent+" specialist started")

    def agent_complete(self, jid: str, worker: str, fence: int,
                       agent: str, result: dict, quality: dict):
        """Store QA verdict + outcome atomically with the agent's completion event."""
        if not isinstance(result, dict) or not isinstance(quality, dict) or quality.get("passed") is not True:
            raise ValueError("Agent result did not pass quality gate")
        raw = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        qa = json.dumps(quality, sort_keys=True, separators=(",", ":"))
        if len(raw.encode()) > 150_000 or len(qa) > 5000:
            raise ValueError("Agent checkpoint exceeds bounded persistence")
        now = time.time()
        with self._tx() as c:
            self._active(c, jid, worker, fence)
            row = c.execute("SELECT status,started FROM agent_steps WHERE job_id=? AND agent=?",
                            (jid,agent)).fetchone()
            if not row or row["status"] != "running":
                raise StaleLease("Agent transition has no running record")
            c.execute("""UPDATE agent_steps SET status='completed',updated=?,finished=?,
                         result_json=?,result_sha256=?,qa_json=? WHERE job_id=? AND agent=?""",
                      (now,now,raw,hashlib.sha256(raw.encode()).hexdigest(),qa,jid,agent))
            self._event(c,jid,"agent_completed",agent+" specialist completed")

    def agent_error(self, jid: str, worker: str, fence: int, agent: str,
                    code: str = "agent_execution_failed"):
        if not isinstance(code, str) or len(code) > 80:
            raise ValueError("Invalid agent failure category")
        with self._tx() as c:
            self._active(c,jid,worker,fence)
            now = time.time()
            c.execute("""UPDATE agent_steps SET status='failed',updated=?,finished=?,error_code=?
                         WHERE job_id=? AND agent=? AND status='running'""",
                      (now,now,code,jid,agent))
            self._event(c,jid,"agent_failed",agent+" specialist failed")

    @staticmethod
    def _settle_agents(c, jid, terminal):
        """No specialist can remain misleadingly queued/running in a terminal job."""
        now = time.time()
        status = "cancelled" if terminal == "cancelled" else "skipped"
        c.execute("""UPDATE agent_steps SET status=?,updated=?,finished=?,
                     error_code=? WHERE job_id=? AND status='queued'""",
                  (status,now,now,"parent_"+terminal,jid))
        c.execute("""UPDATE agent_steps SET status=?,updated=?,finished=?,
                     error_code=? WHERE job_id=? AND status='running'""",
                  (terminal,now,now,"parent_"+terminal,jid))

    def fail(self,jid,worker,fence,error_code="execution_error"):
        with self._tx() as c:
            try:
                row=self._active(c,jid,worker,fence)
                state="failed"
            except InterruptedError:
                state="cancelled"
            except StaleLease:
                return
            c.execute("""UPDATE jobs SET status=?,stage=?,error_code=?,
                lease_owner=NULL,lease_until=0,updated=? WHERE id=? AND fence=?""",
                (state,state,error_code if state=="failed" else "",time.time(),jid,fence))
            self._settle_agents(c, jid, state)
            self._event(c,jid,state,"Execution "+state)

    def artifacts(self,owner,jid):
        self.get(owner,jid)
        with self._tx() as c:
            return [dict(row) for row in c.execute(
                "SELECT id,kind,name,sha256,size FROM artifacts WHERE job_id=? ORDER BY kind",(jid,))]

    def artifact(self,owner,artifact_id):
        with self._tx() as c:
            row=c.execute("""SELECT a.*,j.owner,j.status FROM artifacts a JOIN jobs j ON j.id=a.job_id
                WHERE a.id=? AND j.owner=? AND j.status='completed'""",
                (artifact_id,owner)).fetchone()
            if row is None: raise Missing("Artifact not found")
            p=self.root/"artifacts"/row["owner"]/row["job_id"]/row["name"]
            p=p.resolve()
            if self.root.resolve() not in p.parents:
                raise Missing("Unsafe artifact storage path")
            if not p.exists() and self.objects is not None:
                from .work_objects import StorageUnavailable
                try:
                    self.objects.get(f"artifacts/{row['owner']}/{row['job_id']}/{row['name']}",
                                     p, row["sha256"], row["size"])
                except StorageUnavailable:
                    raise Missing("Artifact unavailable") from None
            if (not p.is_file() or
                    p.stat().st_size!=row["size"] or
                    hashlib.sha256(p.read_bytes()).hexdigest()!=row["sha256"]):
                raise Missing("Artifact integrity check failed")
            return p,dict(row)

    def register_upload(self,owner,name,data:bytes):
        from .security import safe_upload_name
        safe_upload_name(name)
        if not 10 <= len(data) <= 8_000_000:
            raise ValueError("Upload must be 10 bytes to 8 MB")
        if name.lower().endswith(".csv"):
            import csv
            rows=csv.reader(data.decode("utf-8-sig").splitlines())
            header=next(rows,None)
            if not header or len(header)>50: raise ValueError("Invalid CSV header")
        elif name.lower().endswith(".xlsx"):
            import zipfile
            import io
            if not zipfile.is_zipfile(io.BytesIO(data)):
                raise ValueError("Invalid XLSX")
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                files = z.infolist()
                names = z.namelist()
                if z.testzip() is not None or "xl/workbook.xml" not in names or len(names)>500:
                    raise ValueError("Invalid or oversized XLSX archive")
                if sum(i.file_size for i in files)>50_000_000:
                    raise ValueError("Inflated XLSX exceeds 50MB")
                for item in files:
                    parts = item.filename.replace("\\\\", "/").split("/")
                    if (item.filename.startswith("/") or ".." in parts or
                        item.filename.lower().endswith(("vbaproject.bin", ".exe", ".dll")) or
                        item.filename.startswith("xl/externalLinks/") or
                        (item.external_attr >> 16) & 0o170000 == 0o120000):
                        raise ValueError("Unsafe XLSX archive entry")
        else:
            raise ValueError("Only CSV or XLSX uploads supported")
        if self.upload_scanner is not None:
            self.upload_scanner(data)
        with self._tx() as c:
            count=c.execute("SELECT count(*) FROM uploads WHERE owner=?",(owner,)).fetchone()[0]
            if count >= 30: raise Conflict("Upload quota exceeded")
        uid=secrets.token_hex(16)
        path=self.root/"uploads"/owner
        path.mkdir(parents=True,exist_ok=True,mode=0o700)
        final=path/(uid+Path(name).suffix.lower())
        final.write_bytes(data)
        if self.objects is not None:
            self.objects.put(f"uploads/{owner}/{final.name}",
                             final, hashlib.sha256(data).hexdigest(), len(data))
        with self._tx() as c:
            c.execute("INSERT INTO uploads VALUES(?,?,?,?,?,?)",
                      (uid,owner,name,hashlib.sha256(data).hexdigest(),len(data),time.time()))
        return {"id":uid,"name":name,"bytes":len(data)}

    def upload(self,owner,uid):
        with self._tx() as c:
            row=c.execute("SELECT * FROM uploads WHERE id=? AND owner=?",(uid,owner)).fetchone()
            if row is None: raise Missing("Upload not found")
            p=(self.root/"uploads"/owner/(uid+Path(row["name"]).suffix.lower())).resolve()
            if self.root not in p.parents:
                raise Missing("Unsafe upload storage path")
            if not p.exists() and self.objects is not None:
                from .work_objects import StorageUnavailable
                try:
                    self.objects.get(f"uploads/{owner}/{p.name}",p,row["sha256"],row["size"])
                except StorageUnavailable:
                    raise Missing("Upload unavailable") from None
            if (not p.is_file() or
                    p.stat().st_size!=row["size"] or
                    hashlib.sha256(p.read_bytes()).hexdigest()!=row["sha256"]):
                raise Missing("Upload corrupted")
            return p

    def proposal(self,owner,jid,cadence_minutes,max_runs=10):
        if type(cadence_minutes) is not int or not 60<=cadence_minutes<=43200:
            raise ValueError("Cadence outside 1h to 30 days")
        if type(max_runs) is not int or not 1<=max_runs<=30:
            raise ValueError("Maximum scheduled runs must be 1 to 30")
        job=self.get(owner,jid)
        if job["status"]!="completed":
            raise Conflict("Schedule only verified completed work")
        pid=secrets.token_hex(16)
        with self._tx() as c:
            c.execute("""INSERT INTO proposals(id,owner,job_id,cadence_minutes,status,at,max_runs)
                         VALUES(?,?,?,?,'pending_approval',?,?)""",
                      (pid,owner,jid,cadence_minutes,time.time(),max_runs))
        return {"id":pid,"status":"pending_approval","max_runs":max_runs}

    def list_proposals(self,owner):
        with self._tx() as c:
            return [dict(row) for row in c.execute("""SELECT id,job_id,cadence_minutes,status,
                next_run,runs,max_runs FROM proposals WHERE owner=? ORDER BY at DESC LIMIT 50""",
                (owner,))]

    def approve_proposal(self,owner,pid):
        with self._tx() as c:
            row=c.execute("SELECT * FROM proposals WHERE id=? AND owner=?",(pid,owner)).fetchone()
            if not row: raise Missing("Proposal not found")
            if row["status"]!="pending_approval": raise Conflict("Proposal not pending")
            now=time.time()
            c.execute("UPDATE proposals SET status='active',next_run=? WHERE id=?",
                      (now+row["cadence_minutes"]*60,pid))
            return {"id":pid,"status":"active","next_run":now+row["cadence_minutes"]*60}

    def disable_proposal(self,owner,pid):
        with self._tx() as c:
            row=c.execute("SELECT * FROM proposals WHERE id=? AND owner=?",(pid,owner)).fetchone()
            if not row: raise Missing("Proposal not found")
            if row["status"] not in ("active","pending_approval"):
                raise Conflict("Proposal no longer editable")
            c.execute("UPDATE proposals SET status='disabled' WHERE id=?",(pid,))
            return {"id":pid,"status":"disabled"}

    def schedule_due(self,limit=5):
        """Idempotent recurring-job enqueue. One pending invocation per cadence.

        Missed periods are coalesced to one run rather than causing a burst.
        All scheduling and interval updates happen in one DB transaction.
        """
        now=time.time()
        created=[]
        with self._tx() as c:
            due=c.execute("""SELECT p.*,j.payload,j.fingerprint
                FROM proposals p JOIN jobs j ON j.id=p.job_id
                WHERE p.status='active' AND p.next_run<=?
                ORDER BY p.next_run LIMIT ?""",(now,limit)).fetchall()
            for row in due:
                active=c.execute("""SELECT count(*) FROM jobs
                    WHERE owner=? AND status IN ('queued','running')""",
                    (row["owner"],)).fetchone()[0]
                if active>=20:
                    continue
                index=row["runs"]+1
                key="schedule_"+row["id"]+"_"+str(index)
                jid=secrets.token_hex(16)
                c.execute("""INSERT INTO jobs(id,owner,idem,fingerprint,payload,status,stage,created,updated)
                             VALUES(?,?,?,?,?,'queued','accepted',?,?)""",
                          (jid,row["owner"],key,row["fingerprint"],row["payload"],now,now))
                original=c.execute("SELECT plan_json,sha256 FROM job_plans WHERE job_id=?",
                                   (row["job_id"],)).fetchone()
                if original is None or hashlib.sha256(original["plan_json"].encode()).hexdigest()!=original["sha256"]:
                    raise ValueError("Approved job plan missing or corrupted")
                parent_plan=json.loads(original["plan_json"])
                if parent_plan.get("schema_version")==2:
                    # Every scheduled invocation gets a freshly model-authored
                    # plan; never replay a stale strategy without re-evaluation.
                    from .work_dynamic import pending
                    new_plan=pending()
                else:
                    # Only historical jobs retain their immutable approved
                    # template for backward-compatible execution.
                    new_plan=parent_plan
                encoded=json.dumps(new_plan,sort_keys=True,separators=(",",":"))
                c.execute("""INSERT INTO job_plans(job_id,plan_json,sha256,created)
                             VALUES(?,?,?,?)""",
                          (jid,encoded,hashlib.sha256(encoded.encode()).hexdigest(),now))
                for node in new_plan["steps"]:
                    c.execute("""INSERT INTO agent_steps(job_id,agent,status,updated)
                                 VALUES(?,?,'queued',?)""",(jid,node["id"],now))
                self._event(c,jid,"queued","Approved schedule enqueued task")
                new_state="exhausted" if index>=row["max_runs"] else "active"
                c.execute("""UPDATE proposals SET runs=?,next_run=?,status=? WHERE id=?""",
                    (index,now+row["cadence_minutes"]*60,new_state,row["id"]))
                created.append(jid)
        return created
