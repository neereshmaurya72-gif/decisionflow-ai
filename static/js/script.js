document.addEventListener("DOMContentLoaded", function () {
  const sidebar = document.getElementById("sidebar");
  const toggle = document.getElementById("menuToggle");
  const overlay = document.getElementById("mobileOverlay");

  function closeMenu() {
    if (sidebar) sidebar.classList.remove("open");
    document.body.classList.remove("sidebar-open");
  }

  if (toggle) {
    toggle.addEventListener("click", function () {
      if (!sidebar) return;
      const open = sidebar.classList.toggle("open");
      document.body.classList.toggle("sidebar-open", open);
    });
  }

  if (overlay) overlay.addEventListener("click", closeMenu);

  document.querySelectorAll(".sidebar a").forEach(function (link) {
    link.addEventListener("click", closeMenu);
  });
});
