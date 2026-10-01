"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button, Field, Input, Spinner } from "@/components/ui";
import { ApiError, authApi } from "@/lib/api";

export const loginSchema = z.object({
  email: z.email("Enter a valid email address"),
  password: z.string().min(1, "Enter your password"),
});

export const signupSchema = z
  .object({
    display_name: z.string().max(100).optional(),
    email: z.email("Enter a valid email address"),
    password: z.string().min(8, "Use at least 8 characters").max(128),
    confirm: z.string(),
  })
  .refine((v) => v.password === v.confirm, {
    path: ["confirm"],
    message: "Passwords don't match",
  });

type LoginValues = z.infer<typeof loginSchema>;
type SignupValues = z.infer<typeof signupSchema>;
type Mode = "login" | "signup";

/** Only allow same-site relative redirects, never "//evil.com". */
function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";
}

export function AuthForm({ mode }: { mode: Mode }) {
  const router = useRouter();
  const params = useSearchParams();
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const isSignup = mode === "signup";

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<SignupValues | LoginValues>({
    resolver: zodResolver(isSignup ? signupSchema : loginSchema),
    defaultValues: isSignup
      ? { display_name: "", email: "", password: "", confirm: "" }
      : { email: "", password: "" },
  });
  const fieldErrors = errors as Partial<Record<keyof SignupValues, { message?: string }>>;

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const user = isSignup
        ? await authApi.signup({
            email: values.email,
            password: values.password,
            display_name: (values as SignupValues).display_name || null,
          })
        : await authApi.login({ email: values.email, password: values.password });
      queryClient.setQueryData(["me"], user);
      router.replace(safeNext(params.get("next")));
      router.refresh();
    } catch (e) {
      setFormError(e instanceof ApiError ? e.message : "Something went wrong. Try again.");
    }
  });

  const err = (name: keyof SignupValues) => fieldErrors[name]?.message;
  const aria = (name: keyof SignupValues) => ({
    "aria-invalid": err(name) ? true : undefined,
    "aria-describedby": err(name) ? `${name}-error` : undefined,
  });

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm space-y-6">
        <div className="space-y-1 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">
            {isSignup ? "Create your account" : "Log in"}
          </h1>
          <p className="text-sm text-gray-600">
            {isSignup ? "Start tracking receipts in seconds." : "Welcome back to Receipt Tracker."}
          </p>
        </div>

        <form
          onSubmit={onSubmit}
          noValidate
          className="space-y-4 rounded-lg border border-gray-200 bg-white p-6 shadow-sm"
        >
          {formError && (
            <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
              {formError}
            </p>
          )}
          {isSignup && (
            <Field label="Name (optional)" htmlFor="display_name" error={err("display_name")}>
              <Input id="display_name" autoComplete="name" {...register("display_name")} />
            </Field>
          )}
          <Field label="Email" htmlFor="email" error={err("email")}>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              {...aria("email")}
              {...register("email")}
            />
          </Field>
          <Field
            label="Password"
            htmlFor="password"
            error={err("password")}
            hint={isSignup ? "At least 8 characters" : undefined}
          >
            <Input
              id="password"
              type="password"
              autoComplete={isSignup ? "new-password" : "current-password"}
              {...aria("password")}
              {...register("password")}
            />
          </Field>
          {isSignup && (
            <Field label="Confirm password" htmlFor="confirm" error={err("confirm")}>
              <Input
                id="confirm"
                type="password"
                autoComplete="new-password"
                {...aria("confirm")}
                {...register("confirm")}
              />
            </Field>
          )}
          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting && <Spinner />}
            {isSignup ? "Sign up" : "Log in"}
          </Button>
        </form>

        <p className="text-center text-sm text-gray-600">
          {isSignup ? "Already have an account? " : "New here? "}
          <Link
            href={isSignup ? "/login" : "/signup"}
            className="font-medium text-blue-700 underline-offset-2 hover:underline"
          >
            {isSignup ? "Log in" : "Create an account"}
          </Link>
        </p>
      </div>
    </main>
  );
}
