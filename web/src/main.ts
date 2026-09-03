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

setupModal();
