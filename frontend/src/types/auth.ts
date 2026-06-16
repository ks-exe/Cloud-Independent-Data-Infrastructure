export type Role =
  | 'Admin'
  | 'Data_Engineer'
  | 'Operator'
  | 'Auditor'
  | 'Viewer';

export interface User {
  id: string;
  username: string;
  email: string;
  display_name: string;
  role: Role;
  is_active: boolean;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface TokenClaims {
  sub: string;
  username: string;
  role: Role;
  exp: number;
  iat: number;
}

export interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}
