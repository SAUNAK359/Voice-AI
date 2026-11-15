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
  async submit(objective: string, deliverables: string[]) {
    const idem = crypto.randomUUID().replaceAll('-', '');
    return this.json<Job>('/api/work/jobs', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'Idempotency-Key': idem},
      body: JSON.stringify({objective, deliverables})
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
