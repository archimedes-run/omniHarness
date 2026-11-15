import { label } from "./label.js";

function home(root) {
  const stored = Number(localStorage.getItem("count") || "0");
  root.innerHTML = `<h1 id="title">${label}</h1>
    <img id="logo" src="src/logo.svg" width="32" height="32" alt="logo">
    <button id="inc">count is ${stored}</button>
    <a id="to-about" href="/about">About</a>
    <ul id="items"></ul><p id="echo"></p><p id="root-seen"></p>`;
  root.querySelector("#inc").addEventListener("click", (e) => {
    const n = Number(localStorage.getItem("count") || "0") + 1;
    localStorage.setItem("count", String(n));
    e.target.textContent = `count is ${n}`;
  });
  root.querySelector("#to-about").addEventListener("click", (e) => {
    e.preventDefault();
    history.pushState({}, "", "/about");
    about(root);
  });
  fetch("api/items.json")
    .then((r) => r.json())
    .then((d) => {
      root.querySelector("#items").innerHTML = d.items
        .map((i) => `<li>${i}</li>`)
        .join("");
    })
    .catch((e) => {
      root.querySelector("#items").textContent = "items failed: " + e;
    });
  fetch("api/echo", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ hello: "dev server" }),
  })
    .then((r) => r.json())
    .then((d) => {
      root.querySelector("#echo").textContent = "echo " + d.hello;
    })
    .catch((e) => {
      root.querySelector("#echo").textContent = "echo failed: " + e;
    });
}

function about(root) {
  root.innerHTML = `<h2 id="about">About this counter</h2><a id="to-home" href="/">Home</a>`;
  root.querySelector("#to-home").addEventListener("click", (e) => {
    e.preventDefault();
    history.pushState({}, "", "/");
    home(root);
  });
}

// A fresh frame link reaches the page as a message (the host's refresh).
window.addEventListener("message", (e) => {
  if (e.data && e.data.type === "omniharness:preview-root") {
    const seen = document.getElementById("root-seen");
    if (seen) seen.textContent = e.data.root;
  }
});

export function render(root) {
  if (location.pathname.endsWith("/about")) about(root);
  else home(root);
}
