#!/bin/bash

# --- Étape 0 : Vérification Préliminaire ---
echo "--- Étape 0 : Vérification Préliminaire ---"
if ! command -v git &> /dev/null
then
    echo "Git n'est pas installé. Veuillez l'installer d'abord : sudo apt install git"
    exit 1
fi

if [ -d ".git" ]; then
    echo "Un dépôt Git existe déjà dans ce répertoire."
else
    echo "Pas de dépôt Git trouvé. Initialisation..."
    git init
    if [ $? -ne 0 ]; then
        echo "Erreur lors de l'initialisation de Git. Sortie."
        exit 1
    fi
fi
echo ""

# --- Étape 1 : Configuration de Git (si nécessaire) ---
echo "--- Étape 1 : Configuration de Git ---"
read -p "Est-ce votre première fois sur cette machine ou avec ce projet Git ? (oui/non) : " config_needed
if [[ "$config_needed" == "oui" || "$config_needed" == "o" ]]; then
    read -p "Entrez votre nom d'utilisateur Git (ex: John Doe) : " git_user_name
    git config user.name "$git_user_name"
    read -p "Entrez votre adresse email Git (ex: john.doe@example.com) : " git_user_email
    git config user.email "$git_user_email"
    echo "Configuration Git sauvegardée localement pour ce projet."
else
    echo "Utilisation de la configuration Git existante."
fi
echo ""

# --- Étape 2 : Ajout des fichiers au staging area ---
echo "--- Étape 2 : Ajout des fichiers au staging area ---"
echo "Voici l'état actuel de votre dépôt Git :"
git status
echo ""
read -p "Voulez-vous ajouter tous les fichiers modifiés/nouveaux (sauf ceux ignorés par .gitignore) ? (oui/non) : " add_all
if [[ "$add_all" == "oui" || "$add_all" == "o" ]]; then
    git add .
    echo "Tous les fichiers ont été ajoutés au staging area."
else
    echo "Aucun fichier ajouté. Veuillez utiliser 'git add <fichier>' manuellement si vous le souhaitez."
    # Vous pouvez ajouter ici une boucle pour demander des fichiers spécifiques si vous voulez
    exit 0 # Quitte si l'utilisateur ne veut pas ajouter tous les fichiers
fi
echo ""

# --- Étape 3 : Création d'un commit ---
echo "--- Étape 3 : Création d'un commit ---"
read -p "Entrez votre message de commit : " commit_message
if [ -z "$commit_message" ]; then
    commit_message="Initial commit"
    echo "Message de commit vide, utilisation de 'Initial commit'."
fi
git commit -m "$commit_message"
if [ $? -ne 0 ]; then
    echo "Erreur lors de la création du commit. Veuillez vérifier 'git status' et réessayer."
    exit 1
fi
echo "Commit créé avec succès."
echo ""

# --- Étape 4 : Lier le dépôt local à un dépôt distant GitHub ---
echo "--- Étape 4 : Lier le dépôt local à un dépôt distant GitHub ---"

# Vérifier si un dépôt distant est déjà configuré
if git remote get-url origin &> /dev/null; then
    echo "Un dépôt distant 'origin' est déjà configuré : $(git remote get-url origin)"
    read -p "Voulez-vous le changer ou ajouter un nouveau distant ? (changer/ajouter/non) : " remote_action
    if [[ "$remote_action" == "changer" || "$remote_action" == "c" ]]; then
        read -p "Entrez l'URL du nouveau dépôt GitHub (ex: https://github.com/votre_utilisateur/votre_repo.git) : " remote_url
        git remote set-url origin "$remote_url"
        echo "URL distante 'origin' mise à jour."
    elif [[ "$remote_action" == "ajouter" || "$remote_action" == "a" ]]; then
        read -p "Entrez le nom du nouveau distant (ex: upstream) : " remote_name
        read -p "Entrez l'URL du nouveau dépôt GitHub : " remote_url
        git remote add "$remote_name" "$remote_url"
        echo "Nouveau dépôt distant '$remote_name' ajouté."
    else
        echo "Utilisation du dépôt distant existant."
    fi
else
    echo "Aucun dépôt distant 'origin' configuré."
    read -p "Veuillez créer un nouveau dépôt vide sur GitHub (sans README, .gitignore, ou licence).
    Une fois créé, collez l'URL HTTPS ici (ex: https://github.com/votre_utilisateur/votre_repo.git) : " remote_url
    if [ -z "$remote_url" ]; then
        echo "URL distante non fournie. Impossible de pousser les modifications. Sortie."
        exit 1
    fi
    git remote add origin "$remote_url"
    echo "Dépôt distant 'origin' ajouté."
fi
echo ""

# --- Étape 5 : Push des modifications vers GitHub ---
echo "--- Étape 5 : Push des modifications vers GitHub ---"

# Vérifier la branche actuelle
current_branch=$(git rev-parse --abbrev-ref HEAD)
echo "Vous êtes sur la branche : $current_branch"

read -p "Voulez-vous pousser la branche '$current_branch' vers 'origin' ? (oui/non) : " push_confirm
if [[ "$push_confirm" == "oui" || "$push_confirm" == "o" ]]; then
    # Définir la branche distante comme "upstream" pour les pushes futurs
    git push -u origin "$current_branch"
    if [ $? -ne 0 ]; then
        echo "Erreur lors du push vers GitHub. Assurez-vous d'avoir les permissions nécessaires et que l'URL du dépôt est correcte."
        echo "Vous devrez peut-être générer un Personal Access Token (PAT) sur GitHub si vous utilisez l'authentification par mot de passe."
        exit 1
    fi
    echo "Push réussi ! Votre projet est maintenant sur GitHub."
else
    echo "Push annulé. Votre projet n'a pas été envoyé sur GitHub."
fi
echo ""

echo "--- Processus terminé ---"
echo "Vous devriez maintenant pouvoir accéder à votre projet sur GitHub et le cloner sur votre machine Windows."
echo "URL du dépôt : $(git remote get-url origin)"
