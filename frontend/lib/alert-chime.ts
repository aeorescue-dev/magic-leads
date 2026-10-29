/**
 * Chime de alerta in-app (B3).
 *
 * O Web Push nao permite escolher um som proprio (o SO decide). Quando a
 * aplicacao esta aberta, o alerta chega pelo feed em 30 s e aqui toca o chime
 * exclusivo `.mp3` — sintetizado para a Magic Leads (arpejo A5-C#6-E6, sem
 * licencas de terceiros, 13 KB).
 *
 * Autoplay: os browsers so deixam tocar depois de uma interacao. O chime e'
 * "armado" no primeiro clique/tecla (capture, uma vez) para garantir que o
 * primeiro alerta ja toca. Se o browser bloquear, falha em silencio — nunca
 * interrompe a navegacao.
 */

const CHIME_SRC = "/sounds/alert-chime.mp3";
const VOLUME = 0.7;

let audio: HTMLAudioElement | null = null;
let primed = false;

function getAudio(): HTMLAudioElement | null {
  if (typeof window === "undefined") return null;
  if (!audio) {
    audio = new Audio(CHIME_SRC);
    audio.preload = "auto";
    audio.volume = VOLUME;
  }
  return audio;
}

/** Pre-carrega e desbloqueia o audio no primeiro gesto do utilizador. */
export function primeAlertChime(): void {
  if (typeof window === "undefined" || primed) return;
  primed = true;

  const unlock = () => {
    const el = getAudio();
    if (!el) return;
    // Tocar em volume 0 desbloqueia o elemento sem o utilizador ouvir nada.
    const previous = el.volume;
    el.volume = 0;
    el.play()
      .then(() => {
        el.pause();
        el.currentTime = 0;
        el.volume = previous;
      })
      .catch(() => {
        el.volume = previous;
      });
    window.removeEventListener("pointerdown", unlock, true);
    window.removeEventListener("keydown", unlock, true);
  };

  window.addEventListener("pointerdown", unlock, true);
  window.addEventListener("keydown", unlock, true);
}

/** Toca o chime. Devolve false quando o browser bloqueia. */
export function playAlertChime(): boolean {
  const el = getAudio();
  if (!el) return false;
  try {
    el.currentTime = 0;
    const result = el.play();
    if (result && typeof result.catch === "function") {
      result.catch(() => {
        /* autoplay bloqueado: o alerta continua no feed */
      });
    }
    return true;
  } catch {
    return false;
  }
}
