#!/usr/bin/python3

# import argparse
# import bs4
import duckdb
import json
import logging
import os

from gradio import ChatInterface
from langchain import hub
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_community.document_loaders import SitemapLoader
from langchain_community.vectorstores import DuckDB
from langchain_huggingface.embeddings import HuggingFaceEmbeddings
from langchain_huggingface.llms import HuggingFacePipeline
from langchain_text_splitters import RecursiveCharacterTextSplitter

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%m/%d/%Y %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

###################### SETTINGS #######################
# For now avoid gated models that would require a token
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
LANGUAGE_MODEL = "Intel/neural-chat-7b-v3-3"
DOWNLOADS = "docs"
DB = "store.db"
SITE = "https://docs.denvrdata.com/docs/sitemap.xml"


PROMPT_TEMPLATE = """
--- Instructions ---
You are a friendly AI assistant for onboarding new Denvr Dataworks employees. 
Use a conversational tone and provide helpful and informative responses, utilizing external knowledge when possible.

"**Step 1: Parse Context Information** "
Extract and utilize relevant knowledge from the provided context.
**Step 2: Analyze User Query**
Carefully read and comprehend the user's query, pinpointing the key concepts, entities, and intent behind the question.
**Step 3: Determine Response**
If the answer to the user's query can be directly inferred from the context information, provide a concise and accurate response in the same language as the user's query.
**Step 4: Handle Uncertainty**
If you don't know the answer, simply state that you don't know. If the answer is not clear, ask the user for clarification to ensure an accurate response.
**Step 5: Respond in User's Language**
Maintain consistency by ensuring the response is in the same language as the user's query.
**Step 6: Provide Response**
Generate a clear, concise, and informative response to the user's query, adhering to the guidelines outlined above.

--- Context ---
{context}

"""

RESPONSE_TEMPLATE = """
--- Base Model ---
{base_resp}

--- RAG Model ---
{rag_resp_answer}

{rag_resp_refs}
"""

QUERIES = [
    "What is a Large Language Model?",
    "What network bandwidth does Denvr Dataworks offer?",
    "What instance types does Denvr Dataworks offer?",
]

def connect():
    """
    Returns our duckdb connection.
    """

    logger.debug("Establishing DuckDB connection.")
    conn = duckdb.connect(
        database=DB,
        config={
            "enable_external_access": "false",
            "autoinstall_known_extensions": "false",
            "autoload_known_extensions": "false",
        },
    )

    logger.debug("Creating downloads table if not present")
    conn.sql(
        """
        CREATE TABLE IF NOT EXISTS downloads (
            source VARCHAR PRIMARY KEY,
            destination VARCHAR,
            sitename VARCHAR
        );
        """
    )
    
    return conn


def add_site(conn, name, url):
    """
    Adds a new root site to the downloads table.
    """
    logger.info("Adding %s to downloads table", url)
    return conn.execute(
        "INSERT INTO downloads VALUES ( $source, $destination, $sitename )",
        { "source": url, "destination": "", "sitename" : name },
    )


def download(conn):
    parsing_func = lambda x: x.get_text().encode("ascii", "ignore")

    results = conn.sql(
        """
        SELECT source, sitename
        FROM downloads 
        WHERE EXISTS (
            SELECT *
            FROM downloads
            WHERE length(destination) == 0
        )
        """
    )

    count = 0
    for (url, name) in results.fetchall():
        logger.info("Downloading pages from %s", url)
        loader = SitemapLoader(url, parsing_function=parsing_func)
        # loader = RecursiveUrlLoader(
        #     url,
        #     max_depth=2,
        #     extractor=lambda x: bs4.BeautifulSoup(x, "html.parser").text,
        # )

        parent_dir = os.path.join("docs", name)
        os.makedirs(parent_dir, exist_ok=True)

        for document in loader.lazy_load():
            # Extract the source URL
            source = document.metadata['source']
            logger.info("Process %s", source)

            # Determine the local file location, converting to a flat structure.
            relpath = os.path.relpath(source, url).replace("..", "").strip('/').replace("/", "__")
            ext = ".json"

            if relpath in ["", "."]:
                relpath = "index"
            
            destination = os.path.join(parent_dir, relpath + ext)
            logger.info("Saving document to %s", destination)

            # Write the document as a .json file
            with open(destination, "w") as fobj:
                json.dump(dict(document), fobj, ensure_ascii=True, indent=4)

            # Update the downloads table
            conn.execute(
                "INSERT OR REPLACE INTO downloads VALUES ( $source, $destination, $sitename, )",
                { "source": source, "destination": destination, "sitename" : name },
            ).fetchall()

            count += 1
    
    return count


def store(conn, model_name=EMBEDDING_MODEL, device='cpu'):
    """
    Given a duckdb connection create a vectorstore, which is just an interface to a 
    duckdb 'embeddings' table.
    """
    logger.info("Creating a vector store in the duckdb 'embeddings' table.")
    return DuckDB(
        connection=conn,
        embedding=HuggingFaceEmbeddings(
            model_name=model_name, 
            model_kwargs={'device': device},
        ),
    )

def populate(vectorstore, path=DOWNLOADS):
    """
    Split the documents into smaller chunks and store them in the 
    vector store (duckdb embedding table)
    """
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1500,
        chunk_overlap=100,
        length_function=len,
        is_separator_regex=False,
    )

    # Traverse the downloads directory
    for (root, _, files) in os.walk(path):
        for filename in files:
            logger.info("Chunked embeddings for %s", filename)
            with open(os.path.join(root, filename)) as fobj:
                data = json.load(fobj)
                page = Document(**data)
                docs = text_splitter.split_documents([page])
                vectorstore.add_documents(docs)

    return vectorstore


def llm(
    model_name='Intel/neural-chat-7b-v3-3',
    device='hpu',
    bf16=True,
    max_new_tokens=1024,
    max_input_tokens=2048,
    batch_size=1,
    temperature=0.5,
    top_p=0.95,
    use_kv_cache=True,
    use_hpu_graphs=True,
    do_sample=True,
):
    """
    Handles loading the language model as a HuggingFacePipeline wrapping 
    the GaudiTextGenerationPipeline from the optimum-habana examples.
    """
    from gaudi import GaudiTextGenerationPipeline, text_generation_settings
    settings = text_generation_settings()
    settings.model_name_or_path = model_name
    settings.device = device
    settings.bf16 = bf16
    settings.max_new_tokens = max_new_tokens
    settings.max_input_tokens = max_input_tokens
    settings.batch_size = batch_size
    settings.temperature = temperature
    settings.top_p = top_p
    settings.use_kv_cache = use_kv_cache
    settings.use_hpu_graphs = use_hpu_graphs
    settings.do_sample = do_sample


    logging.info("Constructing HuggingFacePipeline for the GaudiTextGenerationPipeline")
    return HuggingFacePipeline(
        pipeline=GaudiTextGenerationPipeline(
            settings, logger,
        )
    )

def rag(model, store, prompt=PROMPT_TEMPLATE):
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", PROMPT_TEMPLATE),
            ("human", "{question}")
        ]
    )
    # A couple helper functions
    retrieve_docs = (lambda query: query["question"]) | store.as_retriever()
    format_docs = lambda docs: "\n\n".join(doc.page_content for doc in docs)

    logging.info("Constructing the final RAG pipeline")
    return RunnablePassthrough.assign(
        context=retrieve_docs,
    ).assign(
        answer=(
            {
                "question": lambda query: query["question"],
                "context": lambda query: format_docs(query["context"]),
            }
            | prompt
            | model.bind(skip_prompt=True)
            | StrOutputParser()
        )
    )

def compare_response(query, base_model, rag_model, response_template):
    base_resp = base_model.invoke(query)
    rag_resp = rag_model.invoke({'question': query})

    return response_template.format(
        base_resp=base_resp,
        rag_resp_answer=rag_resp['answer'],
        rag_resp_refs="\n".join(
            " - {}".format(doc.metadata['source']) 
            for doc in rag_resp['context']
        )
    )


def chatui(base_model, rag_model, response_template=RESPONSE_TEMPLATE):
    return ChatInterface(
        lambda msg, hist: compare_response(
            msg, base_model, rag_model, response_template
        ))

# TODO
# - Update the chain to return a dict of {'question': '...', 'answer': '...', 'context': [...]}
# - Try passing `use_deepspeed`
if __name__ == '__main__':
    model = llm()
    # print(download())

    # documents = CharacterTextSplitter().split_documents(data)
    # embeddings = 

    # store = DuckDB.from_documents(documents, embeddings)
    # query = "What network bandwidth does Denvr Dataworks offer?"
    # print(store.similarity_search(query)[0].page_content)
    # model = llm()
    # model.invoke("What is a Large Language Model?")
    # jupyter notebook --no-browser --NotebookApp.allow_origin='*'
    pass


'''
import yara
conn = yara.connect()
yara.add_site(conn, "denvr", yara.SITE)
yara.download(conn)
vectorstore = yara.store(conn)
yara.populate(vectorstore)
pipeline = yara.rag(yara.llm(), vectorstore)
pipeline.invoke(yara.QUERIES[2])
'''