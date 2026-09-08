export function maskAddress(address: string, showStreetOnly = false): string {
  if (!address) return "";
  const parts = address.split(",");
  const streetPart = parts[0].trim();
  const rest = parts.slice(1).join(", ").trim();
  
  // Separa número do resto (primeira palavra que é só dígitos/hífen)
  const words = streetPart.split(" ");
  if (words.length === 0) return showStreetOnly ? "" : "••••";
  
  const firstWord = words[0];
  const isNumber = /^[\d\-]+$/.test(firstWord);
  
  if (isNumber) {
    const masked = "•".repeat(firstWord.length);
    const streetRest = words.slice(1).join(" ");
    const maskedStreet = streetRest ? `${masked} ${streetRest}` : masked;
    if (showStreetOnly) return maskedStreet;
    return rest ? `${maskedStreet}, ${rest}` : maskedStreet;
  }
  
  // Se não tem número óbvio, retorna como está (ou mascara primeira palavra se for curta)
  if (showStreetOnly) return streetPart;
  return rest ? `${streetPart}, ${rest}` : streetPart;
}

export function maskPhone(phone: string): string {
  if (!phone) return "";
  const digits = phone.replace(/\D/g, "");
  if (digits.length <= 4) return "••••";
  return "•".repeat(digits.length - 4) + digits.slice(-4);
}

export function maskOwnerName(name: string): string {
  if (!name) return "";
  const parts = name.split(" ");
  if (parts.length === 1) return parts[0][0] + "•••";
  return parts.map(p => p[0] + "•••").join(" ");
}