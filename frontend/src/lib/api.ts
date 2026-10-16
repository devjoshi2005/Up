import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const api = axios.create({ baseURL: `${BASE}/api/v1` });

type RetriableConfig = InternalAxiosRequestConfig & { _retry?: boolean };

function getTokens() {
  if (typeof window === "undefined") return { access: null, refresh: null };
  return {
    access: localStorage.getItem("access"),
    refresh: localStorage.getItem("refresh"),
  };
}

export function setTokens(access: string, refresh: string) {
  localStorage.setItem("access", access);
  localStorage.setItem("refresh", refresh);
}

export function clearTokens() {
  localStorage.removeItem("access");
  localStorage.removeItem("refresh");
}

function redirectToLogin() {
  if (typeof window === "undefined") return;
  // Absolute URL keeps this out of the "relative destination" lint rule; the
  // interceptor runs outside React so there is no router to push with.
  window.location.assign(new URL("/login", window.location.origin).href);
}

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const { access } = getTokens();
  if (access) config.headers.Authorization = `Bearer ${access}`;
  return config;
});

let refreshing: Promise<string> | null = null;

api.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const original = error.config as RetriableConfig | undefined;
    if (error.response?.status === 401 && original && !original._retry) {
      original._retry = true;
      const { refresh } = getTokens();
      if (!refresh) {
        clearTokens();
        redirectToLogin();
        return Promise.reject(error);
      }
      refreshing = refreshing || (async () => {
        const r = await axios.post(`${BASE}/api/v1/auth/refresh/`, { refresh });
        setTokens(r.data.access, r.data.refresh ?? refresh);
        return r.data.access;
      })();
      try {
        const newAccess = await refreshing;
        refreshing = null;
        original.headers.Authorization = `Bearer ${newAccess}`;
        return api(original);
      } catch (e) {
        refreshing = null;
        clearTokens();
        redirectToLogin();
        return Promise.reject(e);
      }
    }
    return Promise.reject(error);
  }
);
