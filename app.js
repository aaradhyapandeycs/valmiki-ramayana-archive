const field = document.querySelector("#search");
const output = document.querySelector("#results");
const books = document.querySelector("#books");
const count = document.querySelector("#search-count");

function normalize(text) {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLocaleLowerCase("en");
}

function render(entries) {
  const query = normalize(field.value.trim());
  books.hidden = Boolean(query);
  output.hidden = !query;
  output.replaceChildren();
  count.textContent = "";
  if (!query) return;

  const citation = query.match(/^([1-6])\s*[-.:]\s*(\d+)$/);
  const matches = entries.filter(entry => {
    if (citation) {
      return entry.book_number === Number(citation[1]) && entry.number === Number(citation[2]);
    }
    if (/^\d+$/.test(query)) return entry.number === Number(query);
    const label = normalize(`${entry.book} ${entry.number} ${entry.title} ${(entry.aliases || []).join(" ")}`);
    return query.split(/\s+/).every(term => label.includes(term));
  });

  count.textContent = matches.length + (matches.length === 1 ? " matching sarga" : " matching sargas");
  const list = document.createElement("ol");
  list.className = "search-results";
  for (const entry of matches) {
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.href = entry.url;
    link.textContent = `${entry.book} ${entry.number} · ${entry.title}`;
    item.append(link);
    list.append(item);
  }
  output.append(list);
}

fetch("__BASE__search.json")
  .then(response => {
    if (!response.ok) throw new Error("Chapter index unavailable");
    return response.json();
  })
  .then(entries => {
    field.addEventListener("input", () => render(entries));
    render(entries);
  })
  .catch(() => { count.textContent = "Search is temporarily unavailable. Browse the kāṇḍas below."; });
