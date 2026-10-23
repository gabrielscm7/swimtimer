export async function apiFetch(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch (error) {
      /* resposta sem JSON */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (response.status === 204) return null;
  return response.json();
}

export async function api(method, path, body) {
  const options = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body !== undefined && body !== null) {
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (error) {
      /* resposta sem JSON */
    }
    const error = new Error(
      typeof detail === "string" ? detail : JSON.stringify(detail)
    );
    error.status = response.status;
    throw error;
  }
  if (response.status === 204) return null;
  return response.json();
}
