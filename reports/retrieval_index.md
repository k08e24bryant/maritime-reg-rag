# Retrieval index build

Corpus: 1892 chunks. Machine: Intel64 Family 6 Model 154 Stepping 3, GenuineIntel, GPU: NVIDIA GeForce RTX 3060 Laptop GPU, torch 2.11.0+cu128. Encoder: intfloat/multilingual-e5-base on cuda, fp16, batch size 16. The reranker is not loaded here (query time only).

| step | value |
|---|---|
| BM25 build (tokenize + index) | 0.08 s |
| e5 model load | 12.1 s |
| dense build | 7.2 s total, 7.2 s embedding; 1892 chunks embedded this run, cache ignored (--no-cache, cold run) |
| embedding throughput | 263 chunks/s |
| embedded input length (tokens, incl. prefix + heading) | max 465; 0 over 512 (truncated) |
| index size on disk | 13.1 MB (FAISS 5.5 MB, embedding cache 7.6 MB) |
| peak VRAM (torch.cuda.max_memory_allocated) | 671 MB |
| peak RAM (psutil, process peak working set) | 2399 MB |
