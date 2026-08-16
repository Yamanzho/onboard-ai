"""AI constants shared by embeddings, chunking, and the pgvector column.

Changing ``KB_CHUNK_VECTOR_DIMENSION`` requires a new Alembic revision and a
full reindex of current published versions. Fake and hosted vectors in one
index must share this width; they must not be mixed across models.
"""

# OpenAI text-embedding-3-small native width. FakeEmbeddingProvider uses the
# same size so the column type stays a single vector(n).
KB_CHUNK_VECTOR_DIMENSION = 1536
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
OPENAI_EMBEDDING_DIMENSION = 1536
OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
DEFAULT_EMBEDDING_TIMEOUT_SECONDS = 30.0
SUPPORTED_EMBEDDING_PROVIDERS = frozenset({"fake", "openai"})

# AI-9A/9B LLM. HTTP chat is POST /api/v1/ai/chat. Telegram is a thin client (AI-9C).
OPENAI_LLM_MODEL = "gpt-4o-mini"
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_LLM_TIMEOUT_SECONDS = 30.0
SUPPORTED_LLM_PROVIDERS = frozenset({"fake", "openai"})

# AI-10A reliability. Bounded OpenAI retries; chat budget stays under the
# Telegram HTTP client timeout (30s).
DEFAULT_PROVIDER_MAX_RETRIES = 2
DEFAULT_PROVIDER_RETRY_BACKOFF_SECONDS = 0.2
DEFAULT_PROVIDER_RETRY_MAX_BACKOFF_SECONDS = 2.0
DEFAULT_CHAT_TIMEOUT_SECONDS = 25.0
NO_ANSWER_TOKEN = "NO_ANSWER"
MAX_CONTEXT_DOCUMENTS = 5
MAX_CONTEXT_CHARS_PER_DOC = 1500
MAX_CONTEXT_TOTAL_CHARS = 6000
MAX_CHAT_QUESTION_CHARS = 2000

# AI-11A conversation persistence. User questions stay at 2000; assistant
# replies can be longer than the HTTP question cap (RAG context is 6000 chars).
# 16k is enough for a verbose cited answer and rejects unbounded TEXT blobs.
MAX_CONVERSATION_MESSAGE_CHARS = 16_000
MAX_CONVERSATION_TITLE_CHARS = 200
MAX_CONVERSATION_LIST_LIMIT = 1000
DEFAULT_CONVERSATION_LIST_LIMIT = 100
MAX_CONVERSATION_PREVIEW_CHARS = 160

# AI-11B conversation-aware RAG. History is prompt context only — not KB,
# not ACL, and not a citation source. Newest whole messages are kept.
MAX_CHAT_HISTORY_MESSAGES = 10
MAX_CHAT_HISTORY_CHARS = 12_000

# AI-11C Telegram session pointer. PostgreSQL remains conversation source of
# truth; Redis only remembers which conversation is currently open.
DEFAULT_TELEGRAM_CONVERSATION_TTL_SECONDS = 86_400

# Character windows (not tokens). Onboarding KB articles are usually short
# policies; 1500 chars is one section, overlap keeps a heading with its body.
DEFAULT_CHUNK_SIZE_CHARS = 1500
DEFAULT_CHUNK_OVERLAP_CHARS = 200
MAX_CHUNKS_PER_ARTICLE = 32
SMALL_ARTICLE_CHARS = 1500

# AI-4 internal retriever (no HTTP API). Exact cosine search over the
# ArticleService-allowed current published corpus.
DEFAULT_RETRIEVAL_TOP_K = 5
MAX_RETRIEVAL_TOP_K = 20
MAX_RETRIEVAL_QUERY_CHARS = 2000
# Typical indexed article is 1–3 windows; keep two neighbors of context
# without dumping an entire policy into a future prompt.
MAX_CHUNKS_PER_ARTICLE_RESULT = 2
MAX_RETRIEVAL_CANDIDATES = 100
