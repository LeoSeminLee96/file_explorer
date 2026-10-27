# Ultra-Low-Memory Document Intelligence Requirements

본 애플리케이션은 4GB 이하 RAM을 탑재한 저사양 PC에서도 파일 탐색, 검색, 미리보기 및 문서 요약 기능이 사용 가능해야 한다.

단, AI 요약 기능 때문에 파일 탐색기의 기본 성능이 희생되어서는 안 된다.

최우선 원칙은 다음과 같다.

```text
Explorer/Search
    > Preview
        > Document Parsing
            > AI Summary
```

메모리가 부족한 경우 가장 먼저 AI 기능을 축소하거나 해제하고 파일 탐색과 검색 기능을 유지한다.

---

# 1. Summary Is DOCUMENT-ONLY

AI 요약은 반드시 문서 파일에만 제공한다.

다음 파일에는 AI 요약 기능을 제공하지 않는다.

```text
source code

executables

DLL / shared libraries

archives

disk images

database files

binary data

model files

images

video

audio

fonts

system files

configuration files

temporary files
```

예:

```text
.rs
.py
.js
.ts
.java
.cpp
.c
.h
.go
.cs
.php
.rb
.swift
.kt

.exe
.dll
.so
.dylib

.zip
.7z
.rar
.tar

.db
.sqlite

.gguf
.onnx

.iso
.bin
```

이러한 파일은:

```text
Search       → Allowed
Preview      → Allowed when safe
Metadata     → Allowed
AI Summary   → NOT ALLOWED
```

로 처리한다.

---

# 2. Long Source Code Must Never Enter LLM

소스코드 파일이

```text
1,000 lines
100,000 lines
1,000,000 lines
```

이어도 LLM summarization pipeline으로 보내지 않는다.

소스코드 탐색은 다음 기능까지만 제공한다.

```text
filename search
path search
full-text search
symbol-like text search
preview
metadata
```

따라서 거대한 repository 때문에 LLM worker가 병목되는 일이 없어야 한다.

---

# 3. Document Allowlist

요약 대상의 기본 후보는 다음과 같다.

```text
PDF

DOC
DOCX
ODT
RTF

HWP
HWPX

PPT
PPTX
ODP

XLS
XLSX
ODS

TXT
Markdown
```

하지만 단순 extension만 보고 문서라고 판단하지 않는다.

---

# 4. Strict Document Identification

파일 유형은 최소 다음을 조합하여 판단한다.

```text
extension

magic bytes

MIME / content signature

container structure

parser validation
```

예:

```text
report.exe
```

를

```text
report.pdf
```

로 이름만 변경하더라도 PDF로 간주해서는 안 된다.

반대로 확장자가 없더라도 signature가 유효하면 실제 형식을 식별할 수 있어야 한다.

---

# 5. Plain Text Classification

TXT와 Markdown은 특별하게 처리한다.

다음과 같은 자연어 문서는 요약할 수 있다.

```text
meeting notes
report
article
manual
proposal
research notes
documentation
```

하지만 TXT 파일 내부가 사실상

```text
source code
hex dump
machine log
generated data
configuration
```

라면 요약 기능을 제공하지 않는다.

가벼운 heuristic을 사용한다.

예:

```text
natural language ratio

line-length distribution

punctuation distribution

code token ratio

bracket ratio

identifier density

entropy
```

이 분류를 위해 LLM을 실행하지 않는다.

---

# 6. Document Identity Card

문서를 선택했을 때 먼저 반드시 다음 정보를 보여준다.

```text
Filename
File type
Full path
File size
Modified time
Created time
Document title
Page / slide / sheet count
Detected language
Document category
```

예:

```text
────────────────────────────

2026_AI_Security_Report.pdf

Type
PDF Document

Location
D:\Research\Security\

Size
8.7 MB

Pages
127

Language
Korean / English

Document Type
Technical Report

Modified
2026-10-21

────────────────────────────
```

사용자는 AI 요약을 읽기 전에 항상

> 이것이 어떤 파일에 대한 결과인지

명확하게 알 수 있어야 한다.

---

# 7. Document Type Identification

가능하면 문서의 성격도 식별한다.

예:

```text
Research Paper
Technical Report
Business Report
Manual
Contract
Proposal
Presentation
Spreadsheet
Meeting Notes
Article
General Document
```

단, 확신할 수 없다면 추측하지 않는다.

```text
Document Type: Unknown
```

을 허용한다.

파일 유형 판별은 가능한 경우 metadata와 구조를 우선하며 LLM 판단에 의존하지 않는다.

---

# 8. Summary Header

모든 AI 요약 결과에는 반드시 source identity를 포함한다.

예:

```text
Summary

File:
AI_Security_Report_2026.pdf

Type:
PDF Technical Report

Pages:
127

Modified:
2026-10-21

─────────────────────

Summary
...
```

다른 파일의 캐시된 요약을 잘못 표시하는 문제가 발생하지 않게 한다.

---

# 9. Summary Cache Identity

summary cache는 단순 filename을 key로 사용하지 않는다.

최소:

```text
stable_file_id
content_hash
file_size
modified_time
model_id
model_version
prompt_version
summary_mode
```

를 이용한다.

파일이 변경되면 이전 summary를 사용하지 않는다.

---

# 10. 4GB RAM Is a Primary Target

4GB RAM PC를 compatibility target으로 한다.

애플리케이션이 시스템 RAM 전체를 차지하는 것을 허용하지 않는다.

목표는:

```text
Explorer only:
extremely low memory

Search:
bounded memory

Preview:
bounded memory

Document extraction:
bounded streaming buffers

AI:
only loaded when explicitly required
```

이다.

---

# 11. Memory Profiles

시작 시 사용할 수 있는 시스템 memory를 감지하고 profile을 선택한다.

예:

```text
ULTRA LOW
System RAM <= 4 GB

LOW
4 GB < RAM <= 8 GB

NORMAL
8 GB < RAM <= 16 GB

HIGH
RAM > 16 GB
```

---

# 12. Ultra-Low Profile

4GB 이하에서는 다음 정책을 강제한다.

```text
AI worker count = 1

document parser worker = 1

large preview cache = disabled

embedding model = disabled

semantic index = disabled by default

background AI summarization = disabled

parallel document summarization = disabled
```

동시에 여러 문서를 LLM에 넣지 않는다.

---

# 13. Small Model Policy

4GB 이하에서는 매우 작은 quantized model만 사용한다.

우선 범위:

```text
0.5B ~ 0.8B
```

정도의 CPU-friendly model을 benchmark 대상으로 한다.

기본 quantization:

```text
4-bit
```

또는 실제 benchmark에서 더 나은 memory/quality tradeoff를 가진 형식을 사용한다.

1B 이상의 모델을 반드시 사용해야 한다고 가정하지 않는다.

---

# 14. Model Adapter

특정 모델 이름에 architecture를 종속시키지 않는다.

```text
SummaryModel
    │
    ├── Small CPU Model
    ├── Alternative Small Model
    └── Future Model
```

형태로 abstraction한다.

선택 기준은:

```text
RAM
CPU latency
Korean quality
English quality
summary faithfulness
binary/model size
```

이다.

---

# 15. mmap-Oriented Loading

가능하면 model 전체를 강제로 resident memory에 고정하지 않는다.

지원되는 환경에서는 memory-mapped model loading을 우선 검토한다.

4GB 이하 환경에서는 `mlock`으로 model 전체를 RAM에 고정하는 것을 기본값으로 사용하지 않는다.

OS page cache를 활용하면서 실제 memory pressure를 측정한다.

---

# 16. Small Context Is Mandatory

작은 RAM에서 수십만 token짜리 context를 만들지 않는다.

예를 들어:

```text
Document
500 pages
```

라고 해서 500페이지를 하나의 prompt로 만들지 않는다.

context window는 작은 고정 budget으로 제한한다.

예:

```text
2K ~ 4K effective working context
```

범위부터 benchmark한다.

필요 이상으로 context를 키우지 않는다.

---

# 17. Do Not Solve Long Documents With Huge Context

긴 문서 문제를

```text
increase context to 64K
increase context to 128K
```

방식으로 해결하지 않는다.

이는 저사양 CPU 환경에서

```text
RAM consumption
prompt-processing latency
KV cache
first-token latency
```

를 증가시킬 수 있다.

대신 계층적 처리 구조를 사용한다.

---

# 18. Streaming Document Pipeline

대용량 문서는 다음과 같이 처리한다.

```text
Document

   ↓

Streaming Parser

   ↓

Structural Segments

   ↓

Section Metadata

   ↓

Importance / Coverage Selection

   ↓

Bounded Summary Chunks

   ↓

Hierarchical Merge

   ↓

Final Summary
```

파일 전체 텍스트를 한 번에 RAM에 올리지 않는다.

---

# 19. Structural Segmentation

문서를 단순히 N글자 단위로 자르지 않는다.

다음 구조를 우선 활용한다.

```text
title

abstract

heading

subheading

paragraph

bullet list

table

caption

page

slide

sheet
```

문서 구조가 없는 경우에만 sentence/paragraph 기반 segmentation으로 fallback한다.

---

# 20. Source Anchors

각 segment에 원문 위치를 유지한다.

예:

PDF:

```text
page 1
page 12
page 57
```

PPTX:

```text
slide 3
slide 18
```

DOCX:

```text
heading
paragraph index
```

XLSX:

```text
sheet name
cell range
```

를 유지한다.

---

# 21. Evidence-Aware Summary

요약 결과가 어느 위치에서 나온 것인지 추적 가능해야 한다.

예:

```text
핵심 내용

• 매출은 전년 대비 18% 증가하였다.
  [p. 12]

• 주요 보안 위험은 공급망 공격이다.
  [p. 48-50]
```

모든 문장을 반드시 citation으로 표시할 필요는 없지만 중요한 수치와 주장에는 source anchor를 유지하는 구조를 권장한다.

---

# 22. Accuracy Before Fluent Hallucination

LLM에게 원문에 없는 정보를 보완하도록 요청하지 않는다.

Prompt에는 명확하게 다음 정책을 포함한다.

```text
Use only supplied evidence.

Do not invent missing facts.

Preserve numbers exactly.

Preserve names exactly.

Preserve dates exactly.

If uncertain, omit the claim.

Do not infer facts not supported by the document.
```

---

# 23. Numerical Facts Protection

특히 다음 값은 별도로 추출한다.

```text
dates

money

percentages

measurements

version numbers

counts

proper nouns
```

중요 numeric facts를 LLM이 임의로 변형하지 않도록 한다.

가능하면 deterministic extraction 결과와 AI summary를 cross-check한다.

---

# 24. Fast First-Pass Summary

사용자가 Summary를 누르면 거대한 문서 전체 처리가 끝날 때까지 빈 화면으로 두지 않는다.

먼저 lightweight extraction으로:

```text
title
headings
abstract
executive summary
conclusion
high-value sentences
```

을 활용한 빠른 초벌 summary를 만든다.

이를:

```text
Quick Summary
```

로 표시한다.

---

# 25. Refined Summary

더 상세한 요약이 필요한 경우:

```text
section summaries
        ↓
coverage validation
        ↓
hierarchical reduce
        ↓
final summary
```

를 실행한다.

즉:

```text
FAST RESULT
    ↓
REFINED RESULT
```

형태를 사용할 수 있다.

하지만 UI는 진행 중인 미완성 요약과 완성된 요약을 명확히 구분한다.

---

# 26. Avoid LLM for Every Chunk

1000페이지 문서라고 해서 모든 chunk를 작은 LLM에 무조건 입력하지 않는다.

먼저 inexpensive 단계로 분석한다.

```text
heading importance

section coverage

keyword scoring

sentence scoring

document position

title similarity

numeric-information density

TF-IDF/BM25-like relevance
```

이를 통해 정보 가치가 높은 구간을 선정한다.

---

# 27. Coverage Must Not Be Lost

단순 top-K selection만 사용하면 문서 후반부가 모두 누락될 수 있다.

따라서 다음을 조합한다.

```text
salience

+

structural coverage
```

예:

각 major section에서 최소한 하나 이상의 representative segment를 확보한다.

따라서:

```text
Introduction만 20 chunk

Conclusion 0 chunk
```

같은 편향을 방지한다.

---

# 28. Adaptive Hierarchical Summarization

짧은 문서:

```text
Document
 → one-pass summary
```

중간 문서:

```text
Document
 → section selection
 → summary
```

긴 문서:

```text
Document
 → section summaries
 → summary of summaries
```

초대형 문서:

```text
Document
 → hierarchical tree
 → bounded intermediate summaries
 → final synthesis
```

형태로 자동 전환한다.

---

# 29. Disk-Backed Intermediate State

긴 문서를 처리하며 모든 중간 chunk와 summary를 RAM에 유지하지 않는다.

중간 결과는 필요 시 local DB/cache로 spill한다.

예:

```text
chunk metadata
section summary
source anchors
completion state
```

를 persistent storage에 보관한다.

RAM에는 현재 처리 중인 bounded working set만 유지한다.

---

# 30. Many Documents Must Not Mean Many Models

문서가:

```text
10
1,000
100,000
1,000,000
```

개 있다고 해서 AI model instance를 증가시키지 않는다.

하나의 AI worker를 재사용한다.

```text
Document A
    ↓
AI Worker

Document B
    ↓
same AI Worker

Document C
    ↓
same AI Worker
```

---

# 31. Never Summarize Everything Automatically

문서를 발견했다고 자동으로 모두 LLM 요약하지 않는다.

이것은 금지한다.

```text
Filesystem Scan
    ↓
100,000 Documents
    ↓
100,000 LLM Summaries
```

대신:

```text
Filesystem Scan
    ↓
Metadata Index
    ↓
Content Search Index
```

까지만 수행한다.

AI summary는:

```text
User Request

or

Explicitly Enabled Background Policy
```

에 의해서만 생성한다.

---

# 32. Summary Cache

이미 처리된 문서는 다시 LLM에 넣지 않는다.

```text
Document
   ↓
content hash
   ↓

unchanged?
 ├── yes → cached summary
 └── no  → regenerate
```

파일 수가 많을수록 cache hit ratio가 중요하다.

---

# 33. Partial Cache

500페이지 문서에서 한 section만 변경될 수 있다.

가능하면:

```text
document hash

+

section hashes
```

를 관리한다.

변하지 않은 section summary까지 모두 다시 생성하지 않는 incremental summarization을 검토한다.

---

# 34. Work Queue Must Be Persistent and Bounded

대량 요약 요청도 RAM에 task 수만 개를 적재하지 않는다.

예:

```text
SQLite job queue
```

또는 bounded persistent scheduler를 사용한다.

RAM에는 다음 N개 작업만 가져온다.

```text
pending queue on disk

      ↓

small in-memory queue

      ↓

1 AI Worker
```

---

# 35. User Request Always Wins

Background indexing 또는 background document extraction 중 사용자가 문서를 요약하면:

```text
foreground summary
```

가 우선한다.

우선순위:

```text
1. UI interaction
2. Search
3. Preview
4. User-requested Summary
5. Incremental indexing
6. Background extraction
7. Optional precomputation
```

---

# 36. Hard Memory Budget

4GB 시스템에서는 AI worker에 명시적인 memory ceiling을 둔다.

구체적인 숫자는 benchmark로 결정하되 원칙은:

```text
Never consume all physical memory.

Leave substantial memory for:

Windows/Linux/macOS
WebView/UI
filesystem cache
SQLite
other applications
```

이다.

AI worker가 budget을 넘으면:

```text
reduce context

reduce batch size

clear cache

switch model

fall back to extractive summary
```

순서로 degrade한다.

---

# 37. Extractive Emergency Mode

RAM이 매우 부족하거나 AI 모델을 로드할 수 없다면 요약 기능 자체가 완전히 죽지 않게 한다.

```text
Document
   ↓
Structural Extraction
   ↓
Sentence Ranking
   ↓
Extractive Summary
```

를 제공한다.

이를 UI에서:

```text
Lightweight Summary
```

등으로 명확히 구분할 수 있다.

---

# 38. AI Must Be Unloaded When Necessary

4GB 시스템에서 사용자가 AI summary를 끝내고 일반 탐색만 계속하면 모델을 계속 RAM에 붙잡아 두지 않아도 된다.

일정 idle 기간 이후:

```text
AI Worker
   ↓
release context
   ↓
unmap / terminate worker
```

할 수 있다.

다음 요청에서 다시 lazy-load한다.

---

# 39. Search Index Must Not Duplicate Full Documents Unnecessarily

원문 파일은 filesystem에 이미 존재한다.

검색 인덱스가 전체 문서 내용을 여러 번 복제하지 않도록 한다.

FTS 저장 방식과 metadata storage를 설계할 때:

```text
index size
disk usage
write amplification
```

을 benchmark한다.

가능하면 원문과 검색용 index 사이의 불필요한 duplication을 줄인다.

---

# 40. Document Extraction Cache

문서를 매번 처음부터 parsing하지 않는다.

다음 식별자가 동일하면:

```text
content hash
parser version
```

기존 extraction 결과를 재사용한다.

단, 전체 extracted text를 항상 RAM에 유지하지 않는다.

---

# 41. XLSX Special Handling

Spreadsheet는 문장형 문서처럼 처리하지 않는다.

먼저:

```text
sheet names
used ranges
headers
tables
numeric columns
formulas
summary statistics
```

를 구조적으로 추출한다.

그 뒤 필요한 정보만 summary model에 전달한다.

100만 셀을 모두 prompt에 넣지 않는다.

---

# 42. PPTX Special Handling

Presentation은:

```text
slide title
bullet
speaker notes
table
chart labels
```

중심으로 처리한다.

슬라이드별 구조를 유지한다.

---

# 43. PDF Special Handling

PDF에서는:

```text
page boundaries
headings
paragraphs
tables where extractable
```

를 최대한 유지한다.

OCR이 필요한 scanned PDF는 일반 PDF와 별도 path로 처리한다.

4GB 시스템에서 전체 문서를 한 번에 OCR하지 않는다.

페이지 단위 streaming OCR을 사용한다.

---

# 44. DOCX/HWP Special Handling

가능하면:

```text
document title
heading hierarchy
paragraph
table
footnote
```

구조를 유지한다.

단순 plain text dump 후 의미 구조를 잃지 않도록 한다.

---

# 45. Cancellation

1000페이지 문서를 요약 중 사용자가 다른 파일을 선택했다면 이전 작업은 즉시 foreground priority를 잃는다.

사용자가 Cancel을 누르면:

```text
current generation
parser task
pending chunks
```

를 안전하게 중단한다.

중간 결과 때문에 RAM이나 worker가 남아 있으면 안 된다.

---

# 46. Performance Benchmark Matrix

반드시 다음 파일 크기로 benchmark한다.

```text
1 page
10 pages
100 pages
500 pages
1,000 pages
5,000 pages
```

그리고 다음 file corpus를 사용한다.

```text
100 documents

10,000 documents

100,000 documents
```

측정:

```text
time to first summary

total summary time

peak RSS

CPU utilization

disk reads

cache hit ratio

summary quality

numeric accuracy

section coverage
```

---

# 47. 4GB Machine Must Be Tested for Real

개발자의 32GB/64GB PC에서 정상 동작하는 것을 4GB 호환성으로 간주하지 않는다.

최소 하나의 CI/VM/physical benchmark profile에서 memory limit을 실제:

```text
4 GB
```

로 제한한다.

가능하다면:

```text
2 GB constrained process test
```

도 수행하여 graceful degradation을 검증한다.

---

# 48. Required Failure Test

다음 상황에서도 탐색기는 살아 있어야 한다.

```text
AI model cannot allocate memory

large PDF opened

5,000-page document

100,000 documents indexed

user rapidly changes selected file

parser runs out of memory

AI worker terminates

disk cache full

document modified during summarization
```

---

# 49. UI Policy

Document:

```text
Preview
Summary
```

를 제공한다.

Source Code:

```text
Preview
Search
```

만 제공한다.

Binary:

```text
Metadata
```

중심으로 제공한다.

따라서 UI부터 사용자가 지원되지 않는 파일에 AI summary를 요청하지 못하게 한다.

---

# 50. Summary Button Visibility

summary capability는 다음과 같이 결정한다.

```text
File selected

     ↓

Detect actual format

     ↓

Document?
 ├── No  → Hide/disable Summary
 │
 └── Yes
      ↓
      Safe parser available?
       ├── No → Summary unavailable
       └── Yes → Summary enabled
```

단순 확장자로 버튼을 활성화하지 않는다.

---

# 51. Final Architectural Rule

긴 파일 문제는

```text
more RAM
bigger LLM
larger context
more parallel workers
```

로 해결하지 않는다.

다음으로 해결한다.

```text
streaming

structure awareness

bounded working sets

hierarchical summarization

importance + coverage selection

incremental processing

persistent caching

single reusable AI worker

small quantized model
```

그리고 파일이 아무리 많아도:

```text
File Count ≠ RAM Usage
Document Length ≠ RAM Usage
Folder Depth ≠ Search Latency
```

가 되도록 architecture를 설계한다.

정확히는 위 값들이 처리해야 할 총 작업량에는 영향을 줄 수 있지만,

**메모리 사용량과 interactive latency가 입력 규모에 비례하여 무제한 증가하지 않도록 bounded architecture를 사용한다.**

---

# Definition of Done

다음 조건을 모두 만족해야 한다.

- 4GB RAM 시스템에서 explorer가 정상적으로 실행됨
- GPU가 없어도 정상 동작
- AI 모델이 없어도 탐색/검색 정상 작동
- AI summary는 문서에만 제공
- source code에는 AI summary를 제공하지 않음
- actual file format을 식별함
- summary 화면에 filename/type/path를 표시함
- 수천 페이지 문서를 전체 RAM에 올리지 않음
- 긴 문서의 context를 무작정 증가시키지 않음
- section coverage가 유지됨
- 주요 숫자/날짜/고유명사 검증 로직이 존재함
- 문서 수가 많아도 AI worker 수가 증가하지 않음
- background에서 모든 문서를 자동 요약하지 않음
- unchanged document는 summary cache를 사용함
- AI OOM이 explorer를 죽이지 않음
- parser OOM이 explorer를 죽이지 않음
- low-memory 상황에서 extractive summary로 fallback 가능
- 실제 4GB memory-constrained 환경에서 benchmark 완료