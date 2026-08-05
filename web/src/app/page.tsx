import { redirect } from "next/navigation";

/** Root route — Today is the landing destination. */
export default function Home() {
  redirect("/today");
}
