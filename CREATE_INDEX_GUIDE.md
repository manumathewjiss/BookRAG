# MongoDB Atlas Vector Search Index Setup

## ⚠️ CRITICAL: You Must Create This Index Before the System Will Work!

The migration is complete, but vector search **will not work** until you create the search index in MongoDB Atlas.

## Step-by-Step Instructions:

### 1. Go to MongoDB Atlas
Open: https://cloud.mongodb.com

### 2. Navigate to Search Indexes
- Click on your cluster (sansai.dyvgksv.mongodb.net)
- Click "Search" tab (or "Atlas Search")
- Click "Create Search Index"

### 3. Choose "JSON Editor"
- Select "JSON Editor" (not Visual Editor)
- Click "Next"

### 4. Configure the Index

**Database:** `sanskrity`  
**Collection:** `scripture_vectors`

**JSON Configuration:**
```json
{
  "mappings": {
    "dynamic": false,
    "fields": {
      "embedding": {
        "type": "knnVector",
        "dimensions": 384,
        "similarity": "cosine"
      }
    }
  }
}
```

**Index Name:** `scripture_vectors_vector_index`

### 5. Create the Index
- Click "Next"
- Review settings
- Click "Create Search Index"
- **Wait 2-5 minutes** for index to build

### 6. Repeat for User Context (Optional for now)

If you want file upload functionality, create another index:

**Database:** `sanskrity`  
**Collection:** `user_context_vectors`

**JSON Configuration:**
```json
{
  "mappings": {
    "dynamic": false,
    "fields": {
      "embedding": {
        "type": "knnVector",
        "dimensions": 384,
        "similarity": "cosine"
      }
    }
  }
}
```

**Index Name:** `user_context_vectors_vector_index`

## Verify Index Creation

After a few minutes, you should see:
- Index status: "Active" (green checkmark)
- Index name: `scripture_vectors_vector_index`
- Collection: `sanskrity.scripture_vectors`

## Next Steps

Once the index is active:

1. **Start the server:**
   ```bash
   SansAI/bin/python3 src/server.py
   ```

2. **Open the web app:**
   ```
   http://localhost:8000
   ```

3. **Test a query:**
   - Try asking: "What is dharma?"
   - Check if you get relevant scripture verses

## Troubleshooting

**Index build fails:**
- Check index name matches exactly: `scripture_vectors_vector_index`
- Verify dimensions: 384 (not 1024)
- Ensure similarity is "cosine"

**Queries return no results:**
- Index may still be building (wait 5 min)
- Check server logs for errors
- Verify collection has 93,030 documents

**Connection errors:**
- Check `.env` file has correct MongoDB URL
- Verify network connectivity

## Storage Status

Current MongoDB usage should be around **145-150 MB** with 93k documents.

This is **within the 512MB free tier limit**, but we can still optimize further with chunking if needed!
