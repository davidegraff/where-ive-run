// Small progress cards in the bottom-right corner (import progress, city lookup).

export interface Toast {
  set(label: string, done?: number, total?: number): void;
  note(text: string, warn?: boolean): void;
  close(afterMs?: number): void;
}

export function toast(title: string, opts: { closable?: boolean } = {}): Toast {
  const el = document.createElement("div");
  el.className = "toast";
  el.innerHTML = `<div class="row"><b></b><span></span></div><div class="meter"><i></i></div><div class="note" hidden></div>`;
  el.querySelector("b")!.textContent = title;
  if (opts.closable) {
    const x = document.createElement("button");
    x.className = "x"; x.textContent = "×"; x.title = "Dismiss"; x.setAttribute("aria-label", "Dismiss");
    x.onclick = () => el.remove();
    el.querySelector(".row")!.append(x);
  }
  document.getElementById("status")!.append(el);
  const count = el.querySelector(".row span") as HTMLElement;
  const bar = el.querySelector(".meter i") as HTMLElement;
  const note = el.querySelector(".note") as HTMLElement;
  return {
    set(label, done, total) {
      el.querySelector("b")!.textContent = label;
      if (done !== undefined && total) {
        count.textContent = `${done.toLocaleString()} / ${total.toLocaleString()}`;
        bar.style.width = `${(100 * done) / total}%`;
      } else count.textContent = "";
    },
    note(text, warn = false) {
      note.hidden = false;
      note.textContent = text;
      note.classList.toggle("warn", warn);
    },
    close(afterMs = 0) {
      setTimeout(() => el.remove(), afterMs);
    },
  };
}
