const TOKEN_KEY = 'chatty_token';

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function storeToken(token: string) {
  sessionStorage.setItem(TOKEN_KEY, token);
}
