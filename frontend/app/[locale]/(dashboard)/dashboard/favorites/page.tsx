import { redirect } from "next/navigation";

export default function DashboardFavoritesPage() {
  redirect("/dashboard?fav=1");
}