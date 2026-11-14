const scrollers = document.querySelectorAll(".verse-scroll");

if (scrollers.length > 0 && "ResizeObserver" in window) {
  const update = (area) => {
    const overflow = area.scrollWidth > area.clientWidth + 1;
    if (overflow || area === document.activeElement) {
      area.setAttribute("tabindex", "0");
    } else {
      area.removeAttribute("tabindex");
    }
    area.toggleAttribute("data-overflow", overflow);
  };

  const observer = new ResizeObserver((entries) => {
    for (const {target} of entries) update(target);
  });

  for (const area of scrollers) {
    observer.observe(area);
    area.addEventListener("blur", () => update(area));
  }
  if (document.fonts) {
    document.fonts.ready.then(() => scrollers.forEach(update));
  }
}
