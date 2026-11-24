// Cliente HTTP minimo. Tipos exactos: `npm run gen:api` (con el backend en :8000) genera src/api/schema.d.ts.
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

export const getHealth = () => api<{ status: string; version: string }>('/health')
