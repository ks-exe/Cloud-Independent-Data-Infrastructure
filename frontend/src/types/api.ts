export interface ApiResponse<T> {
  data: T;
  message?: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface ApiError {
  detail: string;
  errors?: ValidationError[];
}

export interface ValidationError {
  error_code: string;
  field_name: string;
  rejected_value: unknown;
  message: string;
}

export interface HealthCheckResponse {
  service_name: string;
  status: 'healthy' | 'unhealthy';
}
