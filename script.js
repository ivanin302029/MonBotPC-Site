
const menuToggle = document.getElementById("menu-toggle");
const navigation = document.getElementById("navigation");
const yearElement = document.getElementById("year");

// Afficher automatiquement l'année actuelle dans le pied de page.
if (yearElement) {
    yearElement.textContent = new Date().getFullYear();
}

// Ouvrir ou fermer le menu sur les petits écrans.
if (menuToggle && navigation) {
    menuToggle.addEventListener("click", () => {
        const menuOuvert = navigation.classList.toggle("open");

        menuToggle.setAttribute(
            "aria-expanded",
            String(menuOuvert)
        );

        menuToggle.setAttribute(
            "aria-label",
            menuOuvert ? "Fermer le menu" : "Ouvrir le menu"
        );
    });

    // Fermer le menu après avoir choisi une section.
    navigation.querySelectorAll("a").forEach((lien) => {
        lien.addEventListener("click", () => {
            navigation.classList.remove("open");
            menuToggle.setAttribute("aria-expanded", "false");
            menuToggle.setAttribute("aria-label", "Ouvrir le menu");
        });
    });
}
