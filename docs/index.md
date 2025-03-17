# Website explorer

Ένα παιχνίδι εξερεύνησης ιστοσελίδων, εμπνευσμένο από το δεινόσαυρο της Google.

## Περιγραφή
Το project έχει ως βάση έναν web crawler που φτιάχτηκε από την αρχή στη γλώσσα Python.  
Με βάση αυτόν δημιουργούνται πίστες τις οποίες ο παίκτης καλείται να εξερευνήσει, με στόχο την κορυφή του leaderboard.  
Οι κανόνες του παιχνιδιού είναι απλοί. Όταν ο παίκτης επισκέπτεται για πρώτη φορά ένα προορισμό (κόμβο) κερδίζει πόντους. Για κάθε συνεχόμενο μοναδικό κόμβο που επισκέπτεται ανεβάζει το σερί (streak) του, το οποίο πολλαπλασιάζει τους κερδισμένους πόντους του. Όσο ο παίκτης απομακρύνεται από την αρχική του τοποθεσία, τόσους περισσότερους πόντους μπορεί να κερδίσει, όπως επίσης μπορεί να βρει κόμβους τηλεμεταφοράς και powerups περιορισμένων κινήσεων. Προσοχή όμως, ανάμεσα στις βοήθειες κρύβονται και παγίδες.  
  
## Εκτέλεση
```sh
# create virtual environment with the venv module
python3 -m venv .venv
source .venv/bin/activate

# install project dependencies
(.venv) pip install -r requirements.txt

# perform database migrations
(.venv) alembic upgrade head

# setup environment variables
(.venv) EXPORT ENV=development

# run application in development mode
(.venv) uvicorn src.main:app --reload
```

## Μελλοντικές Ιδέες
Ακολουθούν σημειώσεις για τη μελλοντική πορεία που μπορεί να έχει η εφαρμογή, σε διάθεση περισσότερο brainstorming παρά roadmap.

**Graph**  
- Treat nodes with the highest centrality (like a navigation bar component) as the main bus   
- Extract graph theme from urls and use it in the game presentation  
- Define cliques/negihbourhoods where special graph-theme based events happen  

**Web Client**  
- [**DONE**] Measure if a head request makes sense before the get request on different sites  
- [**DONE**] The semaphore counter might be exhausted from this approach early in the process  

**HTTP Headers on Client Application**  
- Check content disposition header  
- Use the experimental device memory api through the device-memory header  
- Use the experimental network information api through the downlink header  

**Game**  
- [**DONE**] Add more points further from spawn  
- [**DONE**] Calculate points for nodes lazily; once a player can reach them  
- [**DONE**] Add powerups for searching and moving through the graph  
- [**DONE**] Add traps through the graph, more further from spawn, 3 triggered traps and game over  
- [**DONE**] Fill course with powerups and traps and keep track of them in cache as game setup  
- Bot play session  
- Versus mode with bot, include different strategies  

**Optimizations**  
- Port code to Pypy  
- Reduce the cpu scheduling overhead by ommiting asyncio inside threadpools
- Profile server memory allocations with memray   
- Optimize memory usage before porting to pypy  
- [**DONE**] Strip dependencies from networkx installation  
- Sqlalchemy and memcached transactions  
- Compile sqlalchemy queries and run against schema as a commit hook  