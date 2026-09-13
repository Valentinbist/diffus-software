import htmx from "htmx.org";
import "./styles.css";

// The modal owns history itself (pushState on open, replaceState on swaps
// inside, history.back() on close); htmx must never snapshot a Basic-auth
// page into its own history cache.
htmx.config.historyEnabled = false;
htmx.config.historyCacheSize = 0;
// Swap 4xx/5xx too, so a re-rendered form with a German validation error
// still shows up inside the modal instead of htmx silently discarding it.
htmx.config.responseHandling = [
  { code: "204", swap: false },
  { code: "[23]..", swap: true },
  { code: "[45]..", swap: true, error: true },
];

// htmx.org has no browser-global build in this setup (it's bundled via npm),
// but htmx itself expects to find itself on window for its own extensions.
(window as unknown as { htmx: typeof htmx }).htmx = htmx;

type SwapDetail = {
  target: Element;
  pathInfo: { requestPath: string; responsePath?: string };
};

function setupModal(): void {
  if (!window.matchMedia("(min-width: 900px)").matches) return;

  const modal = document.getElementById("modal");
  const body = document.getElementById("modal-body");
  const close = document.getElementById("modal-close");
  if (!(modal instanceof HTMLDialogElement) || !body || !(close instanceof HTMLAnchorElement)) {
    return;
  }

  close.href = location.href;

  for (const a of document.querySelectorAll<HTMLAnchorElement>("a[data-modal]")) {
    a.setAttribute("hx-get", a.getAttribute("href") ?? "");
    a.setAttribute("hx-target", "#modal-body");
    a.setAttribute("hx-select", ".page");
    a.setAttribute("hx-swap", "innerHTML");
  }
  htmx.process(document.body);

  body.addEventListener("htmx:afterSwap", (e) => {
    const d = (e as CustomEvent<SwapDetail>).detail;
    if (d.target !== body) return;
    const url = d.pathInfo.responsePath ?? d.pathInfo.requestPath;
    if (modal.open) {
      history.replaceState({ modal: true }, "", url);
    } else {
      history.pushState({ modal: true }, "", url);
      modal.showModal();
    }
    modal.scrollTop = 0;
  });

  modal.addEventListener("close", () => {
    if (history.state?.modal) history.back();
  });
  modal.addEventListener("click", (e) => {
    if (e.target === modal) modal.close();
  });
  close.addEventListener("click", (e) => {
    e.preventDefault();
    modal.close();
  });
  window.addEventListener("popstate", () => location.reload());
}

// Filter forms submit themselves on change; their "Anwenden" button is only
// for the no-JS case (base.html marks <html class="js"> so CSS can hide it).
for (const field of document.querySelectorAll<HTMLSelectElement | HTMLInputElement>(
  "form[data-autosubmit] select, form[data-autosubmit] input[type=checkbox]",
)) {
  field.addEventListener("change", () => field.form?.requestSubmit());
}

// Diffus mode: after 5 minutes with no pointer, keyboard, scroll or touch
// input, blur the page — "diffus" is German for "blurry, diffuse", so an
// idle screen quietly turns on-brand instead of just going stale. The next
// such input reverses it and restarts the 5-minute timer.
function setupDiffusMode(): void {
  const IDLE_MS = 5 * 60 * 1000;
  const root = document.documentElement;
  let timer: ReturnType<typeof setTimeout>;

  function wake(): void {
    root.classList.remove("diffus");
    clearTimeout(timer);
    timer = setTimeout(() => root.classList.add("diffus"), IDLE_MS);
  }

  const events = ["pointermove", "pointerdown", "keydown", "scroll", "touchstart", "wheel"] as const;
  for (const type of events) {
    document.addEventListener(type, wake, { passive: true });
  }
  wake();
}

setupModal();
setupDiffusMode();
