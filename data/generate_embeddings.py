#!/usr/bin/env python3
"""
Script pour générer les embeddings des intents à partir du fichier config/intents.yaml
Utilise sentence-transformers avec le modèle paraphrase-multilingual-MiniLM-L12-v2
"""

import yaml
import pickle
from pathlib import Path
from sentence_transformers import SentenceTransformer


def load_intents(yaml_path: str) -> list[dict]:
    """Charge les intents depuis le fichier YAML."""
    with open(yaml_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return config.get('intents', [])


def generate_embeddings(intents: list[dict], model_name: str = "paraphrase-multilingual-MiniLM-L12-v2") -> dict:
    """
    Génère les embeddings pour chaque intent.
    
    Pour chaque intent, on combine le nom, la description et les exemples
    pour créer un embedding représentatif.
    
    Returns:
        dict: Mapping intent_name -> embedding (numpy array)
    """
    print(f"Chargement du modèle: {model_name}")
    model = SentenceTransformer(model_name)
    
    embeddings = {}
    
    for intent in intents:
        name = intent.get('name', '')
        description = intent.get('description', '')
        examples = intent.get('examples', [])
        
        # Texte combiné pour l'embedding: nom + description + exemples
        texts = [f"{name}: {description}"] + examples
        
        print(f"Génération embedding pour intent '{name}' ({len(examples)} exemples)")
        
        # On encode tous les textes et on prend la moyenne
        encoded = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        embedding = encoded.mean(axis=0)
        
        embeddings[name] = embedding
    
    return embeddings


def save_embeddings(embeddings: dict, output_path: str) -> None:
    """Sauvegarde les embeddings dans un fichier pickle."""
    with open(output_path, 'wb') as f:
        pickle.dump(embeddings, f)
    print(f"Embeddings sauvegardés dans: {output_path}")


def main():
    # Chemins
    base_dir = Path(__file__).parent.parent
    yaml_path = base_dir / "config" / "intents.yaml"
    output_path = base_dir / "data" / "intent_embeddings.pkl"
    
    print(f"Chargement des intents depuis: {yaml_path}")
    intents = load_intents(str(yaml_path))
    print(f"{len(intents)} intents trouvés")
    
    print("\nGénération des embeddings...")
    embeddings = generate_embeddings(intents)
    
    print("\nSauvegarde des embeddings...")
    save_embeddings(embeddings, str(output_path))
    
    print(f"\nTerminé! {len(embeddings)} embeddings générés.")


if __name__ == "__main__":
    main()
