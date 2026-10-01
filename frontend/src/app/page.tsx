import { redirect } from "next/navigation";

// Middleware sends logged-out visitors to /login before this runs.
export default function Home() {
  redirect("/receipts");
}
