from qdrant_client import QdrantClient
c = QdrantClient(host='localhost', port=6334, prefer_grpc=True)
for col in c.get_collections().collections:
    c.delete_collection(col.name)
    print(f"Deleted: {col.name}")
print("Done")
