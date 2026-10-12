"use strict";
const lobby = document.getElementById("playtest-lobby");
if (lobby) {
  const check = async () => {
    try {
      const response = await fetch("/api/lobby", {cache: "no-store"});
      if (response.status === 401) { window.location.reload(); return; }
      if (response.ok) {
        const state=await response.json();
        if (state.joined || (lobby.dataset.status === "waiting" && state.status === "started")) {
          window.location.reload(); return;
        }
      }
    } catch (_) { /* Keep the manual refresh link usable while disconnected. */ }
    window.setTimeout(check, 5000);
  };
  window.setTimeout(check, 5000);
}
