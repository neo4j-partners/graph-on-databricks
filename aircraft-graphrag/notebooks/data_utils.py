"""Databricks model wrappers and the SimpleKGPipeline runner.

Used by the retriever notebooks (03-05). Embedding and LLM calls go through the
Databricks Foundation Model APIs via the MLflow deployments client, so these
notebooks must run in a Databricks workspace with those endpoints enabled.

Data loading and the Neo4j connection live in ``data_loader`` (neo4j + stdlib
only) and are re-exported here so the retriever notebooks have a single import.
The loader notebooks (01, 02) import ``data_loader`` directly and need only the
``neo4j`` package.
"""

import asyncio
import concurrent.futures
from typing import Any, Dict, List, Optional, Union

from neo4j_graphrag.embeddings.base import Embedder
from neo4j_graphrag.experimental.components.text_splitters.base import TextSplitter
from neo4j_graphrag.experimental.components.text_splitters.fixed_size_splitter import FixedSizeSplitter
from neo4j_graphrag.experimental.components.types import TextChunks
from neo4j_graphrag.llm.base import LLMInterface, LLMInterfaceV2
from neo4j_graphrag.llm.types import LLMResponse
from neo4j_graphrag.types import LLMMessage

# Re-export the dependency-light helpers so notebooks 03-05 import from one place.
from data_loader import (  # noqa: F401
    GITHUB_DATA_BASE,
    LOCAL_DATA_DIR,
    VOLUME_DATA_PATH,
    Neo4jConnection,
    load_csv,
    load_text,
    resolve_data_base,
)


# =============================================================================
# Default Model Configuration
# =============================================================================

DEFAULT_EMBEDDING_MODEL = "databricks-bge-large-en"
DEFAULT_LLM_MODEL = "databricks-meta-llama-3-3-70b-instruct"

# Databricks BGE and GTE models produce 1024-dimensional vectors
EMBEDDING_DIMENSIONS = 1024


# =============================================================================
# Databricks Embeddings
# =============================================================================

class DatabricksEmbeddings(Embedder):
    """Generate embeddings using Databricks Foundation Model APIs.

    Available models:
    - databricks-bge-large-en: 1024 dims, 512 token context
    - databricks-gte-large-en: 1024 dims, 8192 token context
    """

    def __init__(self, model_id: str = DEFAULT_EMBEDDING_MODEL):
        import mlflow.deployments

        self.model_id = model_id
        self._client = mlflow.deployments.get_deploy_client("databricks")

    def embed_query(self, text: str) -> List[float]:
        """Generate an embedding vector for a single text string."""
        response = self._client.predict(
            endpoint=self.model_id,
            inputs={"input": [text]},
        )
        return response["data"][0]["embedding"]


# =============================================================================
# Databricks LLM
# =============================================================================

class DatabricksLLM(LLMInterface, LLMInterfaceV2):
    """LLM interface using Databricks Foundation Model APIs.

    Implements both LLMInterface (for SimpleKGPipeline) and LLMInterfaceV2 (for
    GraphRAG), so the one class works across notebooks 03-05.
    """

    def __init__(self, model_id: str = DEFAULT_LLM_MODEL):
        import mlflow.deployments

        LLMInterfaceV2.__init__(self, model_name=model_id)
        self.model_id = model_id
        self._client = mlflow.deployments.get_deploy_client("databricks")

    def _predict(self, messages: List[Dict[str, str]]) -> LLMResponse:
        """Send messages to the Databricks endpoint and return the response."""
        response = self._client.predict(
            endpoint=self.model_id,
            inputs={"messages": messages, "max_tokens": 2048},
        )
        content = response["choices"][0]["message"]["content"]
        return LLMResponse(content=content)

    def invoke(
        self,
        input: Union[str, List[LLMMessage]],
        message_history: Optional[Union[List[LLMMessage], Any]] = None,
        system_instruction: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a response, accepting either a string (V1) or message list (V2)."""
        if isinstance(input, list):
            messages = [{"role": m["role"], "content": m["content"]} for m in input]
            return self._predict(messages)

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        if message_history:
            messages.extend(
                {"role": m["role"], "content": m["content"]} for m in message_history
            )
        messages.append({"role": "user", "content": input})
        return self._predict(messages)

    async def ainvoke(
        self,
        input: Union[str, List[LLMMessage]],
        message_history: Optional[Union[List[LLMMessage], Any]] = None,
        system_instruction: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Async version of invoke (runs synchronously)."""
        return self.invoke(
            input,
            message_history=message_history,
            system_instruction=system_instruction,
            **kwargs,
        )


def get_embedder(model_id: str = DEFAULT_EMBEDDING_MODEL) -> DatabricksEmbeddings:
    """Return a Databricks embedder (default: databricks-bge-large-en, 1024 dims)."""
    return DatabricksEmbeddings(model_id=model_id)


def get_llm(model_id: str = DEFAULT_LLM_MODEL) -> DatabricksLLM:
    """Return a Databricks LLM (default: databricks-meta-llama-3-3-70b-instruct)."""
    return DatabricksLLM(model_id=model_id)


# =============================================================================
# Text Splitting
# =============================================================================

def split_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> List[str]:
    """Split text into chunks using FixedSizeSplitter.

    Runs in a worker thread to avoid "asyncio.run() cannot be called from a
    running event loop" inside Jupyter/Databricks.
    """
    splitter = FixedSizeSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap, approximate=True
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(asyncio.run, splitter.run(text)).result()
    return [chunk.text for chunk in result.chunks]


class ContextPrependingSplitter(TextSplitter):
    """Wraps a TextSplitter and prepends a context line to every chunk.

    SimpleKGPipeline passes document_metadata only to the graph builder, never
    into the LLM extraction prompt. Chunks deep in engine-specific sections lose
    the aircraft model, so the LLM confuses engine designations (V2500, CFM56-7B)
    for aircraft types. Prepending a short context header fixes that.
    """

    def __init__(self, inner: TextSplitter, context: str = "") -> None:
        self.inner = inner
        self.context = context

    async def run(self, text: str) -> TextChunks:
        result = await self.inner.run(text)
        if self.context:
            for chunk in result.chunks:
                chunk.text = self.context + chunk.text
        return result


# =============================================================================
# Entity Extraction Schema and Prompt
# =============================================================================

def build_extraction_schema():
    """Build a GraphSchema for SimpleKGPipeline entity extraction.

    Extracts OperatingLimit entities (EGT limits, vibration thresholds, etc.).
    Entity names are qualified with aircraft type so resolution does not merge
    limits from different aircraft.
    """
    from neo4j_graphrag.experimental.components.schema import (
        GraphSchema,
        NodeType,
        PropertyType,
    )

    node_types = [
        NodeType(
            label="OperatingLimit",
            description="An operating parameter limit for an aircraft system.",
            properties=[
                PropertyType(
                    name="name",
                    type="STRING",
                    description=(
                        "Unique identifier combining parameter and aircraft type, "
                        "e.g. 'EGT - A320-200', 'N1Speed - B737-800'. "
                        "Always append ' - <aircraft type>'."
                    ),
                ),
                PropertyType(
                    name="parameterName",
                    type="STRING",
                    description="Base parameter name matching sensor type, e.g. EGT, Vibration, N1Speed, FuelFlow",
                ),
                PropertyType(name="unit", type="STRING", description="Unit of measurement"),
                PropertyType(name="regime", type="STRING", description="Operating regime, e.g. takeoff, cruise"),
                PropertyType(name="minValue", type="STRING", description="Minimum value"),
                PropertyType(name="maxValue", type="STRING", description="Maximum value"),
                PropertyType(name="aircraftType", type="STRING", description="Aircraft type, e.g. A320-200"),
            ],
            additional_properties=False,
        ),
    ]

    return GraphSchema(
        node_types=tuple(node_types),
        relationship_types=(),
        patterns=(),
        additional_node_types=False,
        additional_relationship_types=False,
        additional_patterns=False,
    )


EXTRACTION_PROMPT = """\
You are an expert aviation engineer extracting structured operating-limit \
data from aircraft maintenance manuals to build a knowledge graph.

Your task: extract entities (nodes) and relationships from the input text \
according to the schema below.

Return result as JSON using this format:
{{"nodes": [{{"id": "0", "label": "OperatingLimit", "properties": {{"name": "EGT - A320-200", "parameterName": "EGT", "aircraftType": "A320-200", "unit": "°C", "maxValue": "695"}}}}],
"relationships": []}}

Use only the following node and relationship types:
{schema}

IMPORTANT RULES:

1. DOCUMENT CONTEXT: The input text starts with a [DOCUMENT CONTEXT] line \
that identifies the aircraft type and title. Use the aircraft type from this \
context line as the `aircraftType` property on every extracted entity.

2. AIRCRAFT TYPE vs ENGINE MODEL: The `aircraftType` property must be the \
airframe model (the aircraft you fly, e.g. A320-200, A321neo, B737-800), \
NOT the engine designation (e.g. V2500, LEAP-1A, CFM56-7B, PW1100G). \
Maintenance manuals are organized by aircraft type. Engine models appear \
throughout the text but they are components OF the aircraft, not the \
aircraft type itself.

3. PARAMETER NAMES: The `parameterName` should use the short sensor \
monitoring names from the document's sensor tables (e.g. EGT, Vibration, \
N1Speed, FuelFlow). Prefer concise sensor-style names over verbose \
descriptions.

4. ENTITY NAME FORMAT: The `name` property must follow the pattern \
"<parameterName> - <aircraftType>" (e.g. "EGT - A320-200"). This creates \
a unique identifier per parameter per aircraft type.

5. Only extract entities when the text contains specific numeric limits, \
thresholds, or operating ranges. Do not create entities for general \
descriptions without measurable values.

Assign a unique ID (string) to each node and reuse it for relationships.

Output rules:
- Return ONLY the JSON object, no additional text.
- Omit any backticks — output raw JSON.
- The JSON must be a single object, not wrapped in a list.
- Property names must be in double quotes.

{examples}

Input text:

{text}
"""


# =============================================================================
# SimpleKGPipeline Runner
# =============================================================================

def run_pipeline(
    driver,
    llm: LLMInterface,
    embedder: Embedder,
    text: str,
    document_metadata: Dict[str, str],
    context: str,
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 100,
) -> None:
    """Chunk, embed, and extract entities from text with SimpleKGPipeline.

    Creates Document and Chunk nodes (with embeddings) plus OperatingLimit
    entities in a single pass.
    """
    from neo4j_graphrag.experimental.pipeline.kg_builder import SimpleKGPipeline

    inner_splitter = FixedSizeSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap, approximate=True
    )
    splitter = ContextPrependingSplitter(inner_splitter, context=context)

    pipeline = SimpleKGPipeline(
        llm=llm,
        driver=driver,
        embedder=embedder,
        schema=build_extraction_schema(),
        text_splitter=splitter,
        from_pdf=False,
        on_error="IGNORE",
        perform_entity_resolution=True,
        prompt_template=EXTRACTION_PROMPT,
    )

    print(f"Processing {len(text):,} characters ({document_metadata.get('documentId', 'unknown')})...")
    print(f"  Chunk size: {chunk_size}, overlap: {chunk_overlap}")
    print(f"  LLM: {getattr(llm, 'model_id', getattr(llm, 'model_name', 'unknown'))}")
    print(f"  Embedder: {getattr(embedder, 'model_id', 'unknown')}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(
            asyncio.run,
            pipeline.run_async(text=text, document_metadata=document_metadata),
        ).result()

    print("Pipeline complete!")
