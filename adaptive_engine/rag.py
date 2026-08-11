"""
Lightweight retrieval for RAG: extracts text from an uploaded PDF, splits it
into overlapping chunks, and retrieves the most relevant chunks for a query
using TF-IDF + cosine similarity. Classic IR, no embedding model download
required — keeps this runnable without heavy dependencies.
"""

import io
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> list[str]:
    text = " ".join(text.split())  # normalize whitespace
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return [c for c in chunks if len(c.strip()) > 50]


def retrieve_relevant_chunks(chunks: list[str], query: str, top_k: int = 4) -> list[str]:
    if not chunks:
        return []
    if len(chunks) <= top_k:
        return chunks
    vectorizer = TfidfVectorizer(stop_words="english")
    matrix = vectorizer.fit_transform(chunks + [query])
    scores = cosine_similarity(matrix[-1], matrix[:-1]).flatten()
    top_indices = scores.argsort()[::-1][:top_k]
    return [chunks[i] for i in top_indices]