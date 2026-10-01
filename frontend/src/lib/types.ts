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
