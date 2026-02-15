document.addEventListener("DOMContentLoaded", function () {

  // Smooth scroll for anchor links
  document.querySelectorAll('a[href^="#"]').forEach(function (link) {

    link.addEventListener("click", function (e) {
      const id = this.getAttribute("href");

      // Ignore just "#"
      if (!id || id === "#") return;

      const el = document.querySelector(id);

      if (el) {
        e.preventDefault();
        el.scrollIntoView({
          behavior: "smooth",
          block: "start"
        });
      }
    });

  });

});