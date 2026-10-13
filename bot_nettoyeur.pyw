import os
import json
import time
import queue
import ctypes
import threading
import tkinter as tk

from tkinter import ttk, messagebox
from datetime import datetime

import customtkinter as ctk


# ============================================================
# MON BOT PC — CONFIGURATION
# ============================================================

NOM_APPLICATION = "Mon Bot PC"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COULEURS = {
    "fond": "#0B1120",
    "sidebar": "#111827",
    "carte": "#172033",
    "carte_claire": "#1E293B",
    "bleu": "#3B82F6",
    "bleu_hover": "#2563EB",
    "violet": "#8B5CF6",
    "vert": "#22C55E",
    "rouge": "#EF4444",
    "texte": "#F8FAFC",
    "secondaire": "#94A3B8",
    "bordure": "#334155",
}

DOSSIER_CONFIG = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "MonBotPC"
)

FICHIER_CONFIG = os.path.join(
    DOSSIER_CONFIG,
    "parametres.json"
)

FREQUENCES = {
    "Manuellement (une seule ouverture)": 0,
    "Toutes les 30 minutes": 30 * 60,
    "Toutes les heures": 60 * 60,
    "Toutes les 2 heures": 2 * 60 * 60,
    "Toutes les 4 heures": 4 * 60 * 60,
    "Toutes les 12 heures": 12 * 60 * 60,
    "Toutes les 24 heures": 24 * 60 * 60,
}

FREQUENCE_PAR_DEFAUT = "Toutes les 2 heures"

DOSSIERS_EXCLUS = {
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "$recycle.bin",
    "system volume information",
    "recovery",
    "config.msi",
    "perflogs",
    "appdata",
    "all users",
    "default",
    "default user",
}

EXTENSIONS_PROTEGEES = {
    ".sys", ".dll", ".drv", ".ocx", ".efi", ".mui",
    ".exe", ".msi", ".msp", ".bat", ".cmd", ".ps1",
    ".reg", ".vbs", ".vbe", ".jse", ".wsf", ".com",
    ".scr", ".cpl",
}

TAILLE_LOT = 100


# ============================================================
# VARIABLES
# ============================================================

root = None
contenu = None
sidebar = None

page_actuelle = "accueil"

choix_frequence = FREQUENCE_PAR_DEFAUT
identifiant_minuteur = None
prochain_cycle = None

scan_en_cours = False
evenement_arret_scan = None
application_quitte = False

file_messages = queue.Queue()

fichiers_affiches = {}
fichiers_selectionnes = set()

compteur_erreurs = 0
compteur_dossiers = 0

tableau = None
label_statut = None
label_fichiers = None
label_selection = None
label_erreurs = None
label_prochain_cycle = None

bouton_analyser = None
bouton_selection = None

champ_recherche = None
barre_progression = None

boutons_navigation = {}

historique = []


# ============================================================
# CONFIGURATION
# ============================================================

def charger_config():
    global choix_frequence

    choix_frequence = FREQUENCE_PAR_DEFAUT

    try:
        if os.path.isfile(FICHIER_CONFIG):

            with open(
                FICHIER_CONFIG,
                "r",
                encoding="utf-8"
            ) as fichier:

                donnees = json.load(fichier)

            frequence = donnees.get(
                "frequence",
                FREQUENCE_PAR_DEFAUT
            )

            if frequence in FREQUENCES:
                choix_frequence = frequence

    except (OSError, ValueError, TypeError):
        choix_frequence = FREQUENCE_PAR_DEFAUT


def sauvegarder_config(nouveau_choix):

    os.makedirs(DOSSIER_CONFIG, exist_ok=True)

    donnees = {
        "frequence": nouveau_choix
    }

    temporaire = FICHIER_CONFIG + ".tmp"

    with open(
        temporaire,
        "w",
        encoding="utf-8"
    ) as fichier:

        json.dump(
            donnees,
            fichier,
            ensure_ascii=False,
            indent=4
        )

    os.replace(temporaire, FICHIER_CONFIG)


# ============================================================
# OUTILS
# ============================================================

def taille_lisible(taille):

    unites = ["o", "Ko", "Mo", "Go", "To"]

    valeur = float(taille)

    for unite in unites:

        if valeur < 1024 or unite == unites[-1]:
            return f"{valeur:.1f} {unite}"

        valeur /= 1024

    return f"{valeur:.1f} To"


def chemin_protege(chemin):

    try:
        parties = os.path.normpath(chemin).split(os.sep)

        return any(
            partie.lower() in DOSSIERS_EXCLUS
            for partie in parties
        )

    except (TypeError, ValueError):
        return True


def extension_protegee(chemin):

    extension = os.path.splitext(chemin)[1].lower()

    return extension in EXTENSIONS_PROTEGEES


def obtenir_disques():

    disques = []

    if os.name != "nt":
        return [os.path.abspath(os.sep)]

    try:
        masque = ctypes.windll.kernel32.GetLogicalDrives()

        for numero in range(26):

            if masque & (1 << numero):

                lettre = chr(ord("A") + numero)
                lecteur = f"{lettre}:\\"

                type_lecteur = (
                    ctypes.windll.kernel32.GetDriveTypeW(
                        ctypes.c_wchar_p(lecteur)
                    )
                )

                if type_lecteur in (2, 3):
                    if os.path.exists(lecteur):
                        disques.append(lecteur)

    except Exception:

        lecteur = os.environ.get("SystemDrive", "C:")
        disques = [lecteur + "\\"]

    return disques


# ============================================================
# ANALYSE DES FICHIERS
# ============================================================

def scanner_disques(evenement_arret):

    total = 0
    erreurs = 0

    def signaler_erreur(_erreur):
        nonlocal erreurs
        erreurs += 1

    try:

        disques = obtenir_disques()

        for disque in disques:

            if evenement_arret.is_set():
                break

            file_messages.put((
                "statut",
                f"Analyse du disque {disque}"
            ))

            for dossier, sous_dossiers, noms_fichiers in os.walk(
                disque,
                topdown=True,
                onerror=signaler_erreur,
                followlinks=False
            ):

                if evenement_arret.is_set():
                    break

                sous_dossiers[:] = [
                    nom
                    for nom in sous_dossiers
                    if nom.lower() not in DOSSIERS_EXCLUS
                    and not os.path.islink(
                        os.path.join(dossier, nom)
                    )
                ]

                for nom in noms_fichiers:

                    if evenement_arret.is_set():
                        break

                    chemin = os.path.join(dossier, nom)

                    if chemin_protege(chemin):
                        continue

                    if extension_protegee(chemin):
                        continue

                    try:

                        if os.path.islink(chemin):
                            continue

                        taille = os.path.getsize(chemin)

                        total += 1

                        file_messages.put((
                            "fichier",
                            chemin,
                            taille
                        ))

                    except (OSError, PermissionError):
                        erreurs += 1

    except Exception as erreur:

        file_messages.put((
            "erreur",
            str(erreur)
        ))

    finally:

        file_messages.put((
            "termine",
            total,
            erreurs,
            evenement_arret.is_set()
        ))


# ============================================================
# CORBEILLE WINDOWS
# ============================================================

def envoyer_vers_corbeille(chemins):

    if os.name != "nt":
        raise OSError(
            "Cette fonctionnalité nécessite Windows."
        )

    class SHFILEOPSTRUCTW(ctypes.Structure):

        _fields_ = [
            ("hwnd", ctypes.c_void_p),
            ("wFunc", ctypes.c_uint),
            ("pFrom", ctypes.c_wchar_p),
            ("pTo", ctypes.c_wchar_p),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", ctypes.c_int),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", ctypes.c_wchar_p),
        ]

    chemins_valides = [
        chemin
        for chemin in chemins
        if os.path.isfile(chemin)
        and not os.path.islink(chemin)
        and not chemin_protege(chemin)
        and not extension_protegee(chemin)
    ]

    if not chemins_valides:
        return 0

    liste_chemins = "\0".join(chemins_valides) + "\0\0"

    operation = SHFILEOPSTRUCTW()

    operation.hwnd = root.winfo_id()
    operation.wFunc = 3
    operation.pFrom = liste_chemins

    # FOF_ALLOWUNDO + FOF_NOCONFIRMATION
    # + FOF_SILENT + FOF_NOERRORUI
    operation.fFlags = 0x0040 | 0x0010 | 0x0004 | 0x0400

    resultat = ctypes.windll.shell32.SHFileOperationW(
        ctypes.byref(operation)
    )

    if resultat != 0 or operation.fAnyOperationsAborted:

        raise OSError(
            "Windows n'a pas pu terminer l'opération."
        )

    return len(chemins_valides)


# ============================================================
# COMPOSANTS GRAPHIQUES
# ============================================================

def creer_titre(parent, titre, description=None):

    ctk.CTkLabel(
        parent,
        text=titre,
        font=("Segoe UI", 28, "bold"),
        text_color=COULEURS["texte"]
    ).pack(
        anchor="w",
        pady=(0, 5)
    )

    if description:

        ctk.CTkLabel(
            parent,
            text=description,
            font=("Segoe UI", 13),
            text_color=COULEURS["secondaire"],
            wraplength=750,
            justify="left"
        ).pack(
            anchor="w",
            pady=(0, 20)
        )


def creer_carte(parent, titre, valeur, couleur=None):

    if couleur is None:
        couleur = COULEURS["bleu"]

    carte = ctk.CTkFrame(
        parent,
        fg_color=COULEURS["carte"],
        corner_radius=14,
        border_width=1,
        border_color=COULEURS["bordure"]
    )

    carte.pack(
        side="left",
        fill="both",
        expand=True,
        padx=6
    )

    ctk.CTkLabel(
        carte,
        text=titre,
        font=("Segoe UI", 12),
        text_color=COULEURS["secondaire"]
    ).pack(
        anchor="w",
        padx=18,
        pady=(15, 5)
    )

    valeur_label = ctk.CTkLabel(
        carte,
        text=valeur,
        font=("Segoe UI", 25, "bold"),
        text_color=couleur
    )

    valeur_label.pack(
        anchor="w",
        padx=18,
        pady=(0, 15)
    )

    return valeur_label


def creer_bouton(
    parent,
    texte,
    commande,
    couleur=None,
    largeur=180
):

    if couleur is None:
        couleur = COULEURS["bleu"]

    return ctk.CTkButton(
        parent,
        text=texte,
        command=commande,
        width=largeur,
        height=40,
        corner_radius=10,
        fg_color=couleur,
        hover_color=COULEURS["bleu_hover"],
        font=("Segoe UI", 12, "bold")
    )


def nettoyer_contenu():

    global tableau
    global label_statut
    global label_fichiers
    global label_selection
    global label_erreurs
    global bouton_analyser
    global bouton_selection
    global champ_recherche
    global barre_progression
    global label_prochain_cycle

    for widget in contenu.winfo_children():
        widget.destroy()

    tableau = None
    label_statut = None
    label_fichiers = None
    label_selection = None
    label_erreurs = None
    bouton_analyser = None
    bouton_selection = None
    champ_recherche = None
    barre_progression = None
    label_prochain_cycle = None


# ============================================================
# PAGE ACCUEIL
# ============================================================

def afficher_accueil():

    global page_actuelle
    global label_prochain_cycle

    page_actuelle = "accueil"

    nettoyer_contenu()
    actualiser_navigation()

    creer_titre(
        contenu,
        "Bienvenue sur Mon Bot PC",
        "Analyse et gestion des fichiers de ton ordinateur."
    )

    cadre_bienvenue = ctk.CTkFrame(
        contenu,
        fg_color=COULEURS["carte"],
        corner_radius=18
    )

    cadre_bienvenue.pack(
        fill="x",
        pady=(0, 20)
    )

    ctk.CTkLabel(
        cadre_bienvenue,
        text="Ton assistant de gestion des fichiers",
        font=("Segoe UI", 20, "bold")
    ).pack(
        anchor="w",
        padx=25,
        pady=(25, 8)
    )

    ctk.CTkLabel(
        cadre_bienvenue,
        text=(
            "Explore les fichiers présents sur tes disques, "
            "consulte les résultats et décide toi-même "
            "des opérations à effectuer."
        ),
        font=("Segoe UI", 13),
        text_color=COULEURS["secondaire"],
        wraplength=650,
        justify="left"
    ).pack(
        anchor="w",
        padx=25
    )

    creer_bouton(
        cadre_bienvenue,
        "Lancer une analyse",
        ouvrir_analyse
    ).pack(
        anchor="w",
        padx=25,
        pady=25
    )

    ligne_cartes = ctk.CTkFrame(
        contenu,
        fg_color="transparent"
    )

    ligne_cartes.pack(fill="x", pady=10)

    creer_carte(
        ligne_cartes,
        "Fichiers détectés",
        str(len(fichiers_affiches))
    )

    creer_carte(
        ligne_cartes,
        "Fichiers sélectionnés",
        str(len(fichiers_selectionnes)),
        COULEURS["violet"]
    )

    creer_carte(
        ligne_cartes,
        "Erreurs d'analyse",
        str(compteur_erreurs),
        COULEURS["vert"]
    )

    cadre_info = ctk.CTkFrame(
        contenu,
        fg_color=COULEURS["carte"],
        corner_radius=14
    )

    cadre_info.pack(
        fill="x",
        pady=20
    )

    ctk.CTkLabel(
        cadre_info,
        text="Analyse automatique",
        font=("Segoe UI", 17, "bold")
    ).pack(
        anchor="w",
        padx=20,
        pady=(18, 8)
    )

    ctk.CTkLabel(
        cadre_info,
        text=f"Fréquence actuelle : {choix_frequence}",
        text_color=COULEURS["secondaire"]
    ).pack(
        anchor="w",
        padx=20
    )

    label_prochain_cycle = ctk.CTkLabel(
        cadre_info,
        text="",
        text_color=COULEURS["bleu"]
    )

    label_prochain_cycle.pack(
        anchor="w",
        padx=20,
        pady=(5, 18)
    )

    actualiser_decompte()


# ============================================================
# PAGE ANALYSE
# ============================================================

def ouvrir_analyse():

    global page_actuelle
    global tableau
    global label_statut
    global label_fichiers
    global label_selection
    global label_erreurs
    global bouton_analyser
    global bouton_selection
    global champ_recherche
    global barre_progression

    page_actuelle = "analyse"

    nettoyer_contenu()
    actualiser_navigation()

    creer_titre(
        contenu,
        "Analyse des fichiers",
        "Consulte les fichiers détectés avant toute suppression."
    )

    ligne_cartes = ctk.CTkFrame(
        contenu,
        fg_color="transparent"
    )

    ligne_cartes.pack(
        fill="x",
        pady=(0, 18)
    )

    label_fichiers = creer_carte(
        ligne_cartes,
        "Fichiers trouvés",
        str(len(fichiers_affiches))
    )

    label_selection = creer_carte(
        ligne_cartes,
        "Sélectionnés",
        str(len(fichiers_selectionnes)),
        COULEURS["violet"]
    )

    label_erreurs = creer_carte(
        ligne_cartes,
        "Erreurs",
        str(compteur_erreurs),
        COULEURS["rouge"]
    )

    cadre_statut = ctk.CTkFrame(
        contenu,
        fg_color=COULEURS["carte"],
        corner_radius=12
    )

    cadre_statut.pack(
        fill="x",
        pady=(0, 12)
    )

    label_statut = ctk.CTkLabel(
        cadre_statut,
        text=(
            "Analyse en cours..."
            if scan_en_cours
            else "Prêt à analyser."
        ),
        text_color=COULEURS["secondaire"]
    )

    label_statut.pack(
        anchor="w",
        padx=15,
        pady=(12, 5)
    )

    barre_progression = ctk.CTkProgressBar(
        cadre_statut,
        height=8,
        progress_color=COULEURS["bleu"]
    )

    barre_progression.pack(
        fill="x",
        padx=15,
        pady=(0, 15)
    )

    if scan_en_cours:
        barre_progression.configure(mode="indeterminate")
        barre_progression.start()
    else:
        barre_progression.set(0)

    champ_recherche = ctk.CTkEntry(
        contenu,
        placeholder_text="Rechercher un fichier...",
        height=38,
        corner_radius=10,
        fg_color=COULEURS["carte"]
    )

    champ_recherche.pack(
        fill="x",
        pady=(0, 12)
    )

    champ_recherche.bind(
        "<KeyRelease>",
        filtrer_fichiers
    )

    cadre_tableau = ctk.CTkFrame(
        contenu,
        fg_color=COULEURS["carte"],
        corner_radius=12
    )

    cadre_tableau.pack(
        fill="both",
        expand=True
    )

    style = ttk.Style(root)

    style.theme_use("clam")

    style.configure(
        "MonBot.Treeview",
        background=COULEURS["carte"],
        foreground=COULEURS["texte"],
        fieldbackground=COULEURS["carte"],
        borderwidth=0,
        rowheight=30,
        font=("Segoe UI", 10)
    )

    style.configure(
        "MonBot.Treeview.Heading",
        background=COULEURS["carte_claire"],
        foreground=COULEURS["texte"],
        relief="flat",
        font=("Segoe UI", 10, "bold")
    )

    style.map(
        "MonBot.Treeview",
        background=[
            ("selected", COULEURS["bleu_hover"])
        ],
        foreground=[
            ("selected", "#FFFFFF")
        ]
    )

    colonnes = (
        "choix",
        "nom",
        "taille",
        "chemin"
    )

    tableau = ttk.Treeview(
        cadre_tableau,
        columns=colonnes,
        show="headings",
        style="MonBot.Treeview",
        selectmode="browse"
    )

    tableau.heading("choix", text="Choix")
    tableau.heading("nom", text="Nom du fichier")
    tableau.heading("taille", text="Taille")
    tableau.heading("chemin", text="Emplacement")

    tableau.column(
        "choix",
        width=60,
        minwidth=60,
        anchor="center",
        stretch=False
    )

    tableau.column(
        "nom",
        width=220,
        minwidth=120
    )

    tableau.column(
        "taille",
        width=90,
        minwidth=75,
        anchor="e"
    )

    tableau.column(
        "chemin",
        width=430,
        minwidth=180
    )

    barre_verticale = ttk.Scrollbar(
        cadre_tableau,
        orient="vertical",
        command=tableau.yview
    )

    barre_horizontale = ttk.Scrollbar(
        cadre_tableau,
        orient="horizontal",
        command=tableau.xview
    )

    tableau.configure(
        yscrollcommand=barre_verticale.set,
        xscrollcommand=barre_horizontale.set
    )

    tableau.grid(
        row=0,
        column=0,
        sticky="nsew",
        padx=(10, 0),
        pady=(10, 0)
    )

    barre_verticale.grid(
        row=0,
        column=1,
        sticky="ns",
        pady=(10, 0)
    )

    barre_horizontale.grid(
        row=1,
        column=0,
        sticky="ew",
        padx=(10, 0)
    )

    cadre_tableau.rowconfigure(0, weight=1)
    cadre_tableau.columnconfigure(0, weight=1)

    tableau.bind(
        "<Button-1>",
        basculer_selection
    )

    cadre_actions = ctk.CTkFrame(
        contenu,
        fg_color="transparent"
    )

    cadre_actions.pack(
        fill="x",
        pady=(15, 0)
    )

    bouton_analyser = creer_bouton(
        cadre_actions,
        "Relancer l'analyse",
        lancer_analyse,
        largeur=160
    )

    bouton_analyser.pack(
        side="left",
        padx=(0, 8)
    )

    if scan_en_cours:
        bouton_analyser.configure(state="disabled")

    bouton_selection = creer_bouton(
        cadre_actions,
        "Tout sélectionner",
        basculer_tout,
        COULEURS["violet"],
        largeur=160
    )

    bouton_selection.pack(
        side="left",
        padx=8
    )

    creer_bouton(
        cadre_actions,
        "Vers la Corbeille",
        envoyer_selection_corbeille,
        COULEURS["rouge"],
        largeur=160
    ).pack(
        side="right"
    )

    for identifiant, donnees in fichiers_affiches.items():

        inserer_ligne(
            identifiant,
            donnees
        )

    actualiser_compteurs()


# ============================================================
# TABLEAU
# ============================================================

def inserer_ligne(identifiant, donnees):

    if tableau is None:
        return

    if tableau.exists(identifiant):
        return

    chemin, taille = donnees

    coche = (
        "☑"
        if identifiant in fichiers_selectionnes
        else "☐"
    )

    tableau.insert(
        "",
        "end",
        iid=identifiant,
        values=(
            coche,
            os.path.basename(chemin),
            taille_lisible(taille),
            chemin
        )
    )


def actualiser_compteurs():

    if label_fichiers is not None:
        label_fichiers.configure(
            text=str(len(fichiers_affiches))
        )

    if label_selection is not None:
        label_selection.configure(
            text=str(len(fichiers_selectionnes))
        )

    if label_erreurs is not None:
        label_erreurs.configure(
            text=str(compteur_erreurs)
        )


def actualiser_selection():

    if tableau is not None:

        for identifiant in tableau.get_children():

            valeurs = list(
                tableau.item(
                    identifiant,
                    "values"
                )
            )

            if not valeurs:
                continue

            valeurs[0] = (
                "☑"
                if identifiant in fichiers_selectionnes
                else "☐"
            )

            tableau.item(
                identifiant,
                values=valeurs
            )

    actualiser_compteurs()


def basculer_selection(evenement):

    if tableau is None:
        return

    region = tableau.identify(
        "region",
        evenement.x,
        evenement.y
    )

    if region != "cell":
        return

    colonne = tableau.identify_column(
        evenement.x
    )

    if colonne != "#1":
        return

    identifiant = tableau.identify_row(
        evenement.y
    )

    if identifiant not in fichiers_affiches:
        return

    if identifiant in fichiers_selectionnes:
        fichiers_selectionnes.remove(identifiant)
    else:
        fichiers_selectionnes.add(identifiant)

    actualiser_selection()


def basculer_tout():

    if not fichiers_affiches:
        return

    if len(fichiers_selectionnes) == len(fichiers_affiches):

        fichiers_selectionnes.clear()

        texte = "Tout sélectionner"

    else:

        fichiers_selectionnes.clear()
        fichiers_selectionnes.update(
            fichiers_affiches.keys()
        )

        texte = "Tout désélectionner"

    if bouton_selection is not None:
        bouton_selection.configure(text=texte)

    actualiser_selection()


def filtrer_fichiers(_evenement=None):

    if tableau is None or champ_recherche is None:
        return

    recherche = champ_recherche.get().lower().strip()

    for identifiant in tableau.get_children():
        tableau.delete(identifiant)

    for identifiant, donnees in fichiers_affiches.items():

        chemin, taille = donnees

        if recherche in chemin.lower():

            inserer_ligne(
                identifiant,
                donnees
            )


# ============================================================
# LANCEMENT DE L'ANALYSE
# ============================================================

def lancer_analyse():

    global scan_en_cours
    global evenement_arret_scan
    global compteur_erreurs

    if scan_en_cours:

        messagebox.showinfo(
            NOM_APPLICATION,
            "Une analyse est déjà en cours."
        )

        return

    fichiers_affiches.clear()
    fichiers_selectionnes.clear()

    compteur_erreurs = 0

    while True:
        try:
            file_messages.get_nowait()
        except queue.Empty:
            break

    scan_en_cours = True

    evenement_arret_scan = threading.Event()

    if page_actuelle != "analyse":
        ouvrir_analyse()
    else:
        ouvrir_analyse()

    if label_statut is not None:
        label_statut.configure(
            text="Préparation de l'analyse..."
        )

    thread = threading.Thread(
        target=scanner_disques,
        args=(evenement_arret_scan,),
        daemon=True
    )

    thread.start()


def traiter_messages():

    global scan_en_cours
    global compteur_erreurs

    nombre_traite = 0

    while nombre_traite < 300:

        try:
            message = file_messages.get_nowait()

        except queue.Empty:
            break

        nombre_traite += 1

        type_message = message[0]

        if type_message == "fichier":

            _, chemin, taille = message

            identifiant = (
                f"fichier_{len(fichiers_affiches) + 1}"
            )

            fichiers_affiches[identifiant] = (
                chemin,
                taille
            )

            if page_actuelle == "analyse":

                recherche = ""

                if champ_recherche is not None:
                    recherche = (
                        champ_recherche.get().lower().strip()
                    )

                if recherche in chemin.lower():
                    inserer_ligne(
                        identifiant,
                        (chemin, taille)
                    )

        elif type_message == "statut":

            if label_statut is not None:
                label_statut.configure(
                    text=message[1]
                )

        elif type_message == "erreur":

            if label_statut is not None:
                label_statut.configure(
                    text=f"Erreur : {message[1]}"
                )

        elif type_message == "termine":

            _, total, erreurs, interrompu = message

            scan_en_cours = False
            compteur_erreurs = erreurs

            historique.append({
                "date": datetime.now().strftime(
                    "%d/%m/%Y %H:%M"
                ),
                "fichiers": total,
                "erreurs": erreurs
            })

            if label_statut is not None:

                label_statut.configure(
                    text=(
                        "Analyse interrompue."
                        if interrompu
                        else "Analyse terminée."
                    )
                )

            if barre_progression is not None:

                barre_progression.stop()
                barre_progression.configure(
                    mode="determinate"
                )

                barre_progression.set(
                    0 if interrompu else 1
                )

            if bouton_analyser is not None:
                bouton_analyser.configure(
                    state="normal"
                )

    if page_actuelle == "analyse":
        actualiser_compteurs()

    if not application_quitte:
        root.after(100, traiter_messages)


# ============================================================
# SUPPRESSION SÉCURISÉE
# ============================================================

def envoyer_selection_corbeille():

    if scan_en_cours:

        messagebox.showwarning(
            NOM_APPLICATION,
            "Attends la fin de l'analyse avant de supprimer des fichiers."
        )

        return

    if not fichiers_selectionnes:

        messagebox.showwarning(
            NOM_APPLICATION,
            "Sélectionne d'abord des fichiers."
        )

        return

    chemins = [
        fichiers_affiches[identifiant][0]
        for identifiant in fichiers_selectionnes
        if identifiant in fichiers_affiches
    ]

    confirmation = messagebox.askyesno(
        "Confirmation",
        (
            f"Envoyer {len(chemins)} fichier(s) "
            "vers la Corbeille Windows ?\n\n"
            "ATTENTION : les fichiers détectés ne sont "
            "pas nécessairement inutiles.\n\n"
            "Vérifie leur emplacement avant de continuer."
        )
    )

    if not confirmation:
        return

    try:

        nombre = envoyer_vers_corbeille(
            chemins
        )

        messagebox.showinfo(
            NOM_APPLICATION,
            f"{nombre} fichier(s) envoyé(s) vers la Corbeille."
        )

        lancer_analyse()

    except Exception as erreur:

        messagebox.showerror(
            "Erreur",
            str(erreur)
        )


# ============================================================
# PAGE STATISTIQUES
# ============================================================

def afficher_statistiques():

    global page_actuelle

    page_actuelle = "statistiques"

    nettoyer_contenu()
    actualiser_navigation()

    creer_titre(
        contenu,
        "Statistiques",
        "Consulte les résultats des analyses effectuées pendant cette session."
    )

    ligne = ctk.CTkFrame(
        contenu,
        fg_color="transparent"
    )

    ligne.pack(fill="x")

    creer_carte(
        ligne,
        "Analyses effectuées",
        str(len(historique))
    )

    creer_carte(
        ligne,
        "Fichiers détectés",
        str(len(fichiers_affiches)),
        COULEURS["violet"]
    )

    creer_carte(
        ligne,
        "Erreurs",
        str(compteur_erreurs),
        COULEURS["rouge"]
    )

    cadre = ctk.CTkScrollableFrame(
        contenu,
        fg_color=COULEURS["carte"],
        corner_radius=14
    )

    cadre.pack(
        fill="both",
        expand=True,
        pady=20
    )

    ctk.CTkLabel(
        cadre,
        text="Historique des analyses",
        font=("Segoe UI", 18, "bold")
    ).pack(
        anchor="w",
        padx=15,
        pady=15
    )

    if not historique:

        ctk.CTkLabel(
            cadre,
            text="Aucune analyse terminée pour le moment.",
            text_color=COULEURS["secondaire"]
        ).pack(
            anchor="w",
            padx=15
        )

    for analyse in reversed(historique):

        texte = (
            f"{analyse['date']}   |   "
            f"{analyse['fichiers']} fichiers   |   "
            f"{analyse['erreurs']} erreurs"
        )

        ctk.CTkLabel(
            cadre,
            text=texte,
            anchor="w"
        ).pack(
            fill="x",
            padx=15,
            pady=6
        )


# ============================================================
# PAGE PARAMÈTRES
# ============================================================

def afficher_parametres():

    global page_actuelle

    page_actuelle = "parametres"

    nettoyer_contenu()
    actualiser_navigation()

    creer_titre(
        contenu,
        "Paramètres",
        "Personnalise le fonctionnement de Mon Bot PC."
    )

    cadre = ctk.CTkFrame(
        contenu,
        fg_color=COULEURS["carte"],
        corner_radius=15
    )

    cadre.pack(
        fill="x",
        pady=10
    )

    ctk.CTkLabel(
        cadre,
        text="Fréquence des analyses",
        font=("Segoe UI", 18, "bold")
    ).pack(
        anchor="w",
        padx=20,
        pady=(20, 8)
    )

    variable = tk.StringVar(
        value=choix_frequence
    )

    menu = ctk.CTkOptionMenu(
        cadre,
        variable=variable,
        values=list(FREQUENCES.keys()),
        width=350,
        height=40,
        corner_radius=10
    )

    menu.pack(
        anchor="w",
        padx=20,
        pady=10
    )

    ctk.CTkLabel(
        cadre,
        text=(
            "Le prochain cycle automatique est programmé "
            "après la fermeture de l'analyse.\n"
            "Le mode manuel désactive les analyses automatiques."
        ),
        text_color=COULEURS["secondaire"],
        justify="left",
        wraplength=550
    ).pack(
        anchor="w",
        padx=20,
        pady=10
    )

    def enregistrer():

        global choix_frequence

        nouveau_choix = variable.get()

        if nouveau_choix not in FREQUENCES:
            return

        try:

            sauvegarder_config(
                nouveau_choix
            )

            choix_frequence = nouveau_choix

            planifier_prochain_cycle()

            messagebox.showinfo(
                NOM_APPLICATION,
                "Paramètres enregistrés avec succès !"
            )

        except OSError as erreur:

            messagebox.showerror(
                "Erreur",
                str(erreur)
            )

    creer_bouton(
        cadre,
        "Enregistrer les paramètres",
        enregistrer,
        largeur=230
    ).pack(
        anchor="w",
        padx=20,
        pady=(10, 20)
    )


# ============================================================
# PAGE À PROPOS
# ============================================================

def afficher_apropos():

    global page_actuelle

    page_actuelle = "apropos"

    nettoyer_contenu()
    actualiser_navigation()

    creer_titre(
        contenu,
        "À propos de Mon Bot PC",
        "Informations sur l'application."
    )

    cadre = ctk.CTkFrame(
        contenu,
        fg_color=COULEURS["carte"],
        corner_radius=15
    )

    cadre.pack(
        fill="x",
        pady=10
    )

    ctk.CTkLabel(
        cadre,
        text="Mon Bot PC",
        font=("Segoe UI", 27, "bold"),
        text_color=COULEURS["bleu"]
    ).pack(
        pady=(30, 10)
    )

    ctk.CTkLabel(
        cadre,
        text="Assistant d'analyse et de gestion des fichiers",
        text_color=COULEURS["secondaire"]
    ).pack(pady=5)

    ctk.CTkLabel(
        cadre,
        text=(
            "Mon Bot PC permet d'explorer les fichiers "
            "de ton ordinateur et de gérer leur envoi "
            "vers la Corbeille Windows."
        ),
        wraplength=500,
        justify="center"
    ).pack(
        padx=25,
        pady=20
    )

    ctk.CTkLabel(
        cadre,
        text=(
            "Important : Mon Bot PC ne garantit pas "
            "qu'un fichier détecté peut être supprimé "
            "sans conséquence."
        ),
        text_color=COULEURS["secondaire"],
        wraplength=500,
        justify="center"
    ).pack(
        padx=25,
        pady=(0, 30)
    )


# ============================================================
# PLANIFICATION
# ============================================================

def annuler_minuteur():

    global identifiant_minuteur
    global prochain_cycle

    if identifiant_minuteur is not None:

        try:
            root.after_cancel(
                identifiant_minuteur
            )

        except tk.TclError:
            pass

    identifiant_minuteur = None
    prochain_cycle = None


def planifier_prochain_cycle():

    global identifiant_minuteur
    global prochain_cycle

    annuler_minuteur()

    if application_quitte:
        return

    secondes = FREQUENCES.get(
        choix_frequence,
        0
    )

    if secondes <= 0:
        return

    # Ne pas programmer un nouveau cycle pendant une analyse.
    if scan_en_cours:
        return

    prochain_cycle = time.time() + secondes

    identifiant_minuteur = root.after(
        secondes * 1000,
        lancer_cycle_automatique
    )


def lancer_cycle_automatique():

    global identifiant_minuteur
    global prochain_cycle

    identifiant_minuteur = None
    prochain_cycle = None

    if application_quitte:
        return

    if not scan_en_cours:
        lancer_analyse()


def actualiser_decompte():

    if application_quitte:
        return

    if label_prochain_cycle is None:
        return

    if page_actuelle != "accueil":
        return

    if prochain_cycle is None:

        if choix_frequence == "Manuellement (une seule ouverture)":
            texte = "Mode manuel activé."
        elif scan_en_cours:
            texte = "Analyse en cours."
        else:
            texte = "Aucun cycle programmé."

    else:

        secondes = max(
            0,
            int(prochain_cycle - time.time())
        )

        heures = secondes // 3600
        minutes = (secondes % 3600) // 60
        secondes_restantes = secondes % 60

        texte = (
            f"Prochaine analyse dans : "
            f"{heures:02d}:{minutes:02d}:{secondes_restantes:02d}"
        )

    label_prochain_cycle.configure(
        text=texte
    )

    root.after(
        1000,
        actualiser_decompte
    )


# ============================================================
# NAVIGATION
# ============================================================

def actualiser_navigation():

    for nom, bouton in boutons_navigation.items():

        if nom == page_actuelle:

            bouton.configure(
                fg_color=COULEURS["bleu"],
                text_color="#FFFFFF"
            )

        else:

            bouton.configure(
                fg_color="transparent",
                text_color=COULEURS["secondaire"]
            )


def creer_navigation():

    global sidebar
    global contenu

    sidebar = ctk.CTkFrame(
        root,
        width=230,
        corner_radius=0,
        fg_color=COULEURS["sidebar"]
    )

    sidebar.pack(
        side="left",
        fill="y"
    )

    sidebar.pack_propagate(False)

    ctk.CTkLabel(
        sidebar,
        text="Mon Bot PC",
        font=("Segoe UI", 24, "bold"),
        text_color=COULEURS["bleu"]
    ).pack(
        pady=(35, 5)
    )

    ctk.CTkLabel(
        sidebar,
        text="Gestionnaire de fichiers",
        font=("Segoe UI", 11),
        text_color=COULEURS["secondaire"]
    ).pack(
        pady=(0, 35)
    )

    navigation = [
        ("accueil", "⌂  Accueil", afficher_accueil),
        ("analyse", "⌕  Analyse", ouvrir_analyse),
        (
            "statistiques",
            "▤  Statistiques",
            afficher_statistiques
        ),
        (
            "parametres",
            "⚙  Paramètres",
            afficher_parametres
        ),
        (
            "apropos",
            "ⓘ  À propos",
            afficher_apropos
        ),
    ]

    for nom, texte, commande in navigation:

        bouton = ctk.CTkButton(
            sidebar,
            text=texte,
            command=commande,
            height=45,
            corner_radius=10,
            anchor="w",
            fg_color="transparent",
            hover_color=COULEURS["carte_claire"],
            font=("Segoe UI", 13),
            text_color=COULEURS["secondaire"]
        )

        bouton.pack(
            fill="x",
            padx=15,
            pady=5
        )

        boutons_navigation[nom] = bouton

    creer_bouton(
        sidebar,
        "Quitter",
        quitter_application,
        COULEURS["rouge"],
        largeur=190
    ).pack(
        side="bottom",
        pady=25
    )

    contenu = ctk.CTkFrame(
        root,
        fg_color=COULEURS["fond"],
        corner_radius=0
    )

    contenu.pack(
        side="right",
        fill="both",
        expand=True,
        padx=25,
        pady=25
    )


# ============================================================
# FERMETURE
# ============================================================

def quitter_application():

    global application_quitte

    confirmation = messagebox.askyesno(
        NOM_APPLICATION,
        "Veux-tu vraiment quitter Mon Bot PC ?"
    )

    if not confirmation:
        return

    application_quitte = True

    annuler_minuteur()

    if evenement_arret_scan is not None:
        evenement_arret_scan.set()

    root.destroy()


# ============================================================
# DÉMARRAGE
# ============================================================

def main():

    global root

    charger_config()

    root = ctk.CTk()

    root.title(NOM_APPLICATION)

    root.geometry("1250x780")
    root.minsize(1050, 650)

    root.configure(
        fg_color=COULEURS["fond"]
    )

    creer_navigation()

    afficher_accueil()

    planifier_prochain_cycle()

    root.after(
        100,
        traiter_messages
    )

    root.protocol(
        "WM_DELETE_WINDOW",
        quitter_application
    )

    root.mainloop()


if __name__ == "__main__":
    main()