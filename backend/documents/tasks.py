import os
import ollama
from celery import shared_task
from .models import Document
from .utils import get_vector_store_connection
from langchain_community.document_loaders import PyMuPDFLoader, UnstructuredExcelLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_postgres import PGVector
from langchain_core.documents import Document as LCDocument

@shared_task
def process_document_embedding(doc_id):
    print(f"[WORKER] Starting process for Document {doc_id}")
    doc = Document.objects.get(id=doc_id)
    doc.status = 'processing'
    doc.save()

    try:
        # 1. Load data
        if doc.file_name.endswith('.pdf'):
            loader = PyMuPDFLoader(doc.file.path)
            data = loader.load()
        elif doc.file_name.endswith(('.xlsx', '.xls')):
            loader = UnstructuredExcelLoader(doc.file.path, mode="elements")
            data = loader.load()
        elif doc.file_name.endswith(('.txt', '.csv')):
            # For text files, read them directly and create LCDocument
            with open(doc.file.path, 'r', encoding='utf-8') as f:
                text_content = f.read()
            data = [LCDocument(page_content=text_content, metadata={"source": doc.file_name})]
        else:
            raise ValueError(f"Unsupported file type: {doc.file_name}")
        
        print(f"[WORKER] Loaded {len(data)} documents from {doc.file_name}")

        # 2. Split text
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
        splits = text_splitter.split_documents(data)
        print(f"[WORKER] Split document {doc_id} into {len(splits)} chunks")

        # 3. Generate Embeddings using official Ollama Library
        # We extract the strings to send to the batch embed endpoint
        texts = [split.page_content for split in splits]
        
        client = ollama.Client(host=os.getenv("OLLAMA_BASE_URL"))
        
        response = client.embed(
            model=os.getenv("EMBEDDING_MODEL", "embeddinggemma"),
            input=texts
        )
        print(f"[WORKER] Generated {len(response['embeddings'])} embeddings for document {doc_id}")
        
        # 4. Store in PGVector
        # We pair the generated embeddings back with their metadata
        connection = get_vector_store_connection()
        print(f"[WORKER] Initializing vector store with connection: {connection.split('@')[0]}...")

        vector_store = PGVector(
            collection_name="rag_collection",
            connection=connection,
            embeddings=None, 
            use_jsonb=True,
        )

        # Zip together text, embeddings, and original metadata
        embeddings_list = response['embeddings']
        metadatas = []
        for split in splits:
            meta = split.metadata
            meta.update({
                "user_id": str(doc.user.id),
                "document_id": str(doc.id),
                "file_name": doc.file_name
            })
            metadatas.append(meta)

        try:
            vector_store.add_embeddings(
                texts=texts,
                embeddings=embeddings_list,
                metadatas=metadatas
            )
            doc.status = 'completed'
            print(f"[WORKER] Successfully stored {len(splits)} chunks in vector DB for Document {doc_id}")
        except Exception as store_error:
            print(f"[WORKER] Error storing embeddings in vector DB: {store_error}")
            raise store_error
        
    except Exception as e:
        print(f"[WORKER] Error processing document {doc_id}: {e}")
        import traceback
        traceback.print_exc()
        doc.status = 'failed'
    
    doc.save()