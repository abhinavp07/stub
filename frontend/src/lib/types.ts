// Mirrors backend/app/schemas. Keep in sync.
// Money and quantities arrive as decimal strings (e.g. "12.30"), never floats.

export type Money = string;
export type ISODate = string; // YYYY-MM-DD
export type ISODateTime = string;

export interface HealthResponse {
  status: "ok";
}

export interface User {
  id: string;
  email: string;
  display_name: string | null;
  currency: string;
}

export interface SignupRequest {
  email: string;
  password: string;
  display_name?: string | null;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export type ReceiptStatus = "pending_upload" | "processing" | "ready" | "failed";

export interface UploadUrlRequest {
  filename: string;
  content_type: string;
  size_bytes: number;
}

export interface UploadUrlResponse {
  receipt_id: string;
  upload_url: string;
  fields: Record<string, string>;
}

export interface LineItem {
  id: string;
  position: number;
  description: string;
  quantity: string | null;
  unit_price: Money | null;
  amount: Money | null;
}

export interface LineItemInput {
  description: string;
  quantity?: string | null;
  unit_price?: Money | null;
  amount?: Money | null;
}

export interface ReceiptSummary {
  id: string;
  status: ReceiptStatus;
  error_message: string | null;
  original_filename: string;
  content_type: string;
  merchant: string | null;
  purchase_date: ISODate | null;
  total: Money | null;
  currency: string;
  category_id: string | null;
  tags: string[];
  needs_review: boolean;
  created_at: ISODateTime;
  thumbnail_url: string | null;
}

export type ExtractedField = "merchant" | "purchase_date" | "subtotal" | "tax" | "tip" | "total";

export interface ReceiptDetail extends ReceiptSummary {
  subtotal: Money | null;
  tax: Money | null;
  tip: Money | null;
  notes: string | null;
  field_confidence: Partial<Record<ExtractedField, number>>;
  user_edited_fields: string[];
  line_items: LineItem[];
  updated_at: ISODateTime;
  image_url: string | null;
  low_confidence_fields: ExtractedField[];
}

export interface ReceiptUpdate {
  merchant?: string | null;
  purchase_date?: ISODate | null;
  subtotal?: Money | null;
  tax?: Money | null;
  tip?: Money | null;
  total?: Money | null;
  category_id?: string | null;
  notes?: string | null;
  tags?: string[];
  needs_review?: boolean;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface Category {
  id: string;
  name: string;
  color: string; // #rrggbb
  is_default: boolean;
  receipt_count: number;
}

export interface CategoryInput {
  name?: string;
  color?: string;
}

export type ReceiptSort = "purchase_date" | "total";

/** Query filters for GET /receipts. category_id "none" means uncategorized. */
export interface ReceiptFilters {
  q?: string;
  category_id?: string;
  date_from?: ISODate;
  date_to?: ISODate;
  min_total?: string;
  max_total?: string;
  status?: Exclude<ReceiptStatus, "pending_upload">;
  needs_review?: boolean;
  tag?: string;
  sort?: ReceiptSort;
}

export interface InsightsSummary {
  month: string; // YYYY-MM
  currency: string;
  total: Money;
  receipt_count: number;
  previous_month: string;
  previous_total: Money;
  previous_receipt_count: number;
  change_pct: string | null;
  needs_review_count: number;
}

export interface CategoryTotal {
  category_id: string | null;
  name: string;
  color: string;
  total: Money;
  receipt_count: number;
}

export interface ByCategory {
  currency: string;
  total: Money;
  items: CategoryTotal[];
}

export interface TrendPoint {
  month: string;
  total: Money;
  receipt_count: number;
  by_category: { category_id: string | null; total: Money }[] | null;
}

export interface Trend {
  currency: string;
  months: TrendPoint[];
}

export type BudgetStatus = "ok" | "warning" | "over";

export interface Budget {
  category_id: string;
  category_name: string;
  color: string;
  monthly_limit: Money;
  alert_threshold_pct: number;
  month: string;
  spent: Money;
  remaining: Money;
  percent_used: string;
  status: BudgetStatus;
}

export interface BudgetInput {
  monthly_limit: Money;
  alert_threshold_pct?: number;
}
