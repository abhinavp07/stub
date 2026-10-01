import type { ButtonHTMLAttributes, InputHTMLAttributes } from "react";
import { forwardRef } from "react";

type Variant = "primary" | "secondary" | "danger" | "ghost";

const variants: Record<Variant, string> = {
  primary: "bg-gray-900 text-white hover:bg-gray-700 disabled:bg-gray-400",
  secondary:
    "border border-gray-300 bg-white text-gray-900 hover:bg-gray-50 disabled:text-gray-400",
  danger: "bg-red-600 text-white hover:bg-red-700 disabled:bg-red-300",
  ghost: "text-gray-700 hover:bg-gray-100 disabled:text-gray-400",
};

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type="button"
      className={`inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:cursor-not-allowed ${variants[variant]} ${className}`}
      {...props}
    />
  );
}

export const inputClass =
  "block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm shadow-xs placeholder:text-gray-400 focus:border-blue-600 focus:outline-2 focus:outline-blue-600/30 aria-[invalid=true]:border-red-500";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className = "", ...props }, ref) {
    return <input ref={ref} className={`${inputClass} ${className}`} {...props} />;
  },
);

export function Field({
  label,
  htmlFor,
  error,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  error?: string;
  hint?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label htmlFor={htmlFor} className="block text-sm font-medium text-gray-700">
        {label}
      </label>
      {children}
      {hint && !error && <p className="text-xs text-gray-500">{hint}</p>}
      {error && (
        <p id={`${htmlFor}-error`} className="text-xs text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden className={`animate-pulse rounded bg-gray-200 ${className}`} />;
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent ${className}`}
    />
  );
}
