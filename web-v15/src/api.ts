export type Auth = { accessKey: string; sessionId: string };

export type Job = {
  id: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  stage: string;
  error_code: string | null;
  updated: number;
  result?: string;
};

export type Agent = {
  agent: string;
  status: string;
  attempt: number;
  error_code?: string;
  started?: number;
  finished?: number;
};

export type PlanStep = {
  id: string;
  tool: string;
  depends_on: string[];
  thinking_level?: 'medium' | 'high';
};

export type Plan = { status: 'planning' | 'ready'; steps: PlanStep[] };
export type Artifact = { id: string; kind: string; name: string; size: number; sha256: string };
export type Quality = { job_id: string; status: string; quality: Record<string, unknown> | null };
export type PageInfo = { pages: number; format: string; renderer: string; fidelity: string };

export class WorkApi {
  constructor(readonly auth: Auth) {}

  async request(path: string, init: RequestInit = {}): Promise<Response> {
    if (!path.startsWith('/api/work/')) throw Error('Invalid Work API path');
    const headers = new Headers(init.headers);
    if (this.auth.accessKey) {
      headers.set('x-rizzler-key', this.auth.accessKey);
      headers.set('x-session-id', this.auth.sessionId);
    } else if (init.method && init.method !== 'GET') {
      const token = document.cookie.split('; ').find(x => x.startsWith('rizzler_csrf='));
      if (token) headers.set('x-csrf-token', decodeURIComponent(token.split('=').slice(1).join('=')));
    }
    const result = await fetch(path, {
      ...init, headers, credentials: 'same-origin', cache: 'no-store'
    });
    if (!result.ok) throw Error('Work request unavailable (HTTP ' + result.status + ')');
    return result;
  }

  async json<T>(path: string, init?: RequestInit): Promise<T> {
    return (await this.request(path, init)).json() as Promise<T>;
  }

  jobs() { return this.json<{jobs: Job[]}>('/api/work/jobs'); }
  job(id: string) { return this.json<Job>('/api/work/jobs/' + encodeURIComponent(id)); }
  plan(id: string) { return this.json<Plan>('/api/work/jobs/' + encodeURIComponent(id) + '/plan'); }
  agents(id: string) { return this.json<{agents: Agent[]}>('/api/work/jobs/' + encodeURIComponent(id) + '/agents'); }
  artifacts(id: string) { return this.json<{artifacts: Artifact[]}>('/api/work/jobs/' + encodeURIComponent(id) + '/artifacts'); }
  quality(id: string) { return this.json<Quality>('/api/work/jobs/' + encodeURIComponent(id) + '/quality'); }
  pages(id: string) { return this.json<PageInfo>('/api/work/artifacts/' + encodeURIComponent(id) + '/pages'); }
  preview(id: string) { return this.json<unknown>('/api/work/artifacts/' + encodeURIComponent(id) + '/preview'); }
  image(id: string, page: number) {
    return this.request('/api/work/artifacts/' + encodeURIComponent(id) + '/pages/' + page).then(r => r.blob());
  }
  async uploadDataset(file: File): Promise<string> {
    if (file.size < 1 || file.size > 8_000_000) {
      throw Error('CSV/XLSX analysis sources must be under 8 MB');
    }
    const result = await this.json<{id:string}>('/api/work/uploads', {
      method: 'POST', headers: {'X-File-Name': file.name}, body: file
    });
    return result.id;
  }

  private async sha256(blob: Blob): Promise<string> {
    const digest = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
    return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2,'0')).join('');
  }

  async uploadSource(file: File): Promise<string> {
    if (file.size < 1 || file.size > 200_000_000) {
      throw Error('Selected source exceeds the 200 MB upload limit');
    }
    if (file.size <= 8_000_000) {
      const record = await this.json<{id:string}>('/api/work/sources', {
        method: 'POST', headers: {'X-File-Name': file.name}, body: file
      });
      return record.id;
    }
    // Resumable, checksummed 1 MB transfers. The server verifies the complete
    // digest and scans uploaded bytes before indexing; no optimistic success.
    const digest = await this.sha256(file);
    const transfer = await this.json<{id:string;offset:number}>(
      '/api/work/sources/transfers', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body:JSON.stringify({name:file.name,bytes:file.size,sha256:digest})
      });
    let offset = transfer.offset || 0;
    let failures = 0;
    while (offset < file.size) {
      const chunk = file.slice(offset,Math.min(offset + 1_000_000,file.size));
      try {
        const result = await this.json<{offset:number}>(
          '/api/work/sources/transfers/' + encodeURIComponent(transfer.id) + '/chunks',{
            method:'PUT',headers:{
              'X-Chunk-Offset':String(offset),
              'X-Chunk-Sha256':await this.sha256(chunk)
            },body:chunk
          });
        if (result.offset <= offset || result.offset > file.size) {
          throw Error('Invalid server acknowledgement during source transfer');
        }
        offset = result.offset; failures=0;
      } catch (error) {
        if (++failures > 3) throw error;
        const status = await this.json<{offset:number}>(
          '/api/work/sources/transfers/' + encodeURIComponent(transfer.id));
        if (status.offset < 0 || status.offset > file.size) throw Error('Invalid resume position');
        offset = status.offset;
      }
    }
    const source = await this.json<{id:string}>(
      '/api/work/sources/transfers/' + encodeURIComponent(transfer.id) + '/complete',{
        method:'POST'
      });
    return source.id;
  }

  async submit(objective: string, deliverables: string[], options: {
    uploads?: string[]; source_ids?: string[];
    source_coverage?: 'targeted'|'complete';
    evidence_scope?: 'auto'|'uploaded_only'|'external_allowed';
  } = {}) {
    const idem = crypto.randomUUID().replaceAll('-', '');
    return this.json<Job>('/api/work/jobs', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'Idempotency-Key': idem},
      body: JSON.stringify({objective, deliverables, ...options})
    });
  }
  async download(artifact: Artifact) {
    const response = await this.request('/api/work/artifacts/' + encodeURIComponent(artifact.id));
    const data = await response.blob();
    const url = URL.createObjectURL(data);
    try {
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = artifact.name;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } finally {
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  }
}
