export type FlagCode = "us" | "br" | "es";

export default function LpFlag({
  code,
  className = "h-3.5 w-5",
}: {
  code: FlagCode;
  className?: string;
}) {
  if (code === "br") {
    return (
      <svg className={className} viewBox="0 0 28 20" aria-hidden>
        <rect width="28" height="20" rx="2.5" fill="#009B3A" />
        <polygon points="14,3.2 24.6,10 14,16.8 3.4,10" fill="#FEDD00" />
        <circle cx="14" cy="10" r="3.7" fill="#002776" />
      </svg>
    );
  }
  if (code === "es") {
    return (
      <svg className={className} viewBox="0 0 28 20" aria-hidden>
        <rect width="28" height="20" rx="2.5" fill="#AA151B" />
        <rect y="5" width="28" height="10" fill="#F1BF00" />
      </svg>
    );
  }
  return (
    <svg className={className} viewBox="0 0 28 20" aria-hidden>
      <rect width="28" height="20" rx="2.5" fill="#B22234" />
      {[1.54, 4.62, 7.7, 10.77, 13.85, 16.92].map((y) => (
        <rect key={y} y={y} width="28" height="1.54" fill="#fff" />
      ))}
      <rect width="12" height="10.8" rx="1.5" fill="#3C3B6E" />
    </svg>
  );
}
