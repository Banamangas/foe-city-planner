export function pickRoot(pathname: string): "advanced" | "wizard" {
  return pathname === "/advanced" || pathname.startsWith("/advanced/") ? "advanced" : "wizard";
}
