# Web Crawler

Ο web crawler, ή από εδώ και πέρα αράχνη, είναι η βάση του όλου πρότζεκτ και από όπου ξεκίνησε η όλη ιδέα για το παιχνίδι. Μία πρώτη υλοποίηση μπορεί να βρεθεί στο repository [antsinar/dayProjects](https://github.com/antsinar/dayProjects)

Χωρίζεται σε δύο βασικά modules, την αράχνη καθ'αυτή, που τρέχει τη διαδικασία ανάκτησης σελίδων από το domain στόχό, και τον processor, που αναλαμβάνει τη καταχώρηση και τη προώθηση εργασιών προς εκτέλεση. 

## Αντιμετώπιση Ιστοσελίδας Στόχου

## Σχεδιαστικές Επιλογές
Ο σχεδιασμός του module έπρεπε σε πρώτη φάση να υπακούει στα 3 ακόλουθα στοιχεία:

1. Να είναι επεκτάσιμο και αντικαταστήσιμο
2. Να τρέχει εντός του process του webserver
3. Να μην επιβαρύνει το async event loop και να μην αφήνει σφάλματα στο runtime

Για το πρώτο σημείο εφαρμόστηκε μια decoupled λογική. Η αράχνη δεν εκτελείται έως ότου λάβει μια εργασία από τον processor. Ο processor με τη σειρά του έχει το ρόλο να λαμβάνει τα αιτήματα του χρήστη και να περιορίζει πόσες (παραμετροποιημένες) εκδόσεις της αράχνης εκτελούνται με βάση configuration. Οι εκδοχές των δύο modules χρησιμοποιούν wrapper συναρτήσεις για να καλύψουν λειτουργικές λεπτομέριες, οπότε και θα είναι σχετικά ανώδυνο να αντικατασταθούν στο μέλλον.

Στο δεύτερο σημείο έπρεπε να συμορφωθούμε στο τεχνιτό περιορισμό των δυνατοτήτων της εφαρμογής. Με τη χρήση εξωτερικής ουράς μηνυμάτων (RabbitMQ, Redis κτλ) θα μπορούσαμε τρέξουμε περισσότερα tasks αράχνης που να είναι πραγματικά ανεξάρτητα μεταξύ τους. Παρόλα αυτά η ουρά διαχείρησης των εργασιών θα παραμείνει in-memory ώστε να μην υπάρχει το κόστος και το overhead ενός ακόμη service. Χάνετε δηλαδή προσωρινά η δυνατότητα πραγματικά παράλληλης επεξεργασίας, άρα και κλιμάκωσης της εφαρμογής, σε αντάλλαγμα για ένα πιο άμεσο και οικονομικό λειτουργικό πρωτότυπο.

Το τρίτο σημείο, σε συνδυασμό με το δεύτερο, ήταν το πιο ιδιαίτερο στην επίλυση. 
Χρονολογικά, ένα url εισέρχεται στην ουρά μηνυμάτων του processor ώστε να δημιουργηθεί μια εργασία. **Πως παρακολουθούμε όμως την ουρά μηνυμάτων για νέα μηνύματα;** 
Έπειτα, η εργασία καλείτε με ασύγχρονο τρόπο, χωρίς να περιμένουμε απαραίτητα ένα επιτυχημένο αποτέλεσμα. **Πως διασφαλίζουμε πως ένα task που υπάρχει απλά στο runtime δε θα προκαλέσει σφάλματα και στην υπόλοιπη εφαρμογή, από τη στιγμή που το περιβάλλον εκτέλεσης μοιράζεται;** Και τέλος, μπορεί μια αράχνη να είναι μια κατά βάση I/O διαδικασία, λόγω συνδέσεων στο δίκτυο, όμως η επεξερασία html εγγράφων και εξαγωγή link από αυτούς δεν είναι. **Πως περιορίζεται η κατανάλωση πόρων επεξεργαστή και επομένως οι blocking διαδικασίες εντός του event loop;** Μια σύντομη απάντηση θα ήταν με τη χρήση γρήγορων compiled βιβλιοθηκών και έξυπνη αναζήτηση εντός του εγγράφου, όμως περισσότερες λεπτομέριες υπάρχουν παρακάτω στην υλοποίηση της αράχνης.

### Στρατηγική Εξερεύνησης
Τη δεδομένη στιγμή που γράφεται αυτή η περιγραφή, ο αλγόριθμος που διατρέχει κάθε site θα μπορούσε να χαρακτηριστεί ως greedy/eager. Και αυτό διότι αποφασίζει πια σελίδα να επισκευθεί οπορτουνιστικά, δηλαδή την πρώτη διαθέσιμη. Αυτό δεν αποτελεί optimal στρατηγική και χρήση των διαθέσιμων resources, είναι όμως μια βάση που λειτουργεί.

...

### Υλοποίηση Αράχνης
Η λογική του αλγορίθμου της αράχνης ενσωματώνεται στη κλάση `Crawler`, ενώ υπάρχουν και βοηθητικές συναρτήσεις `generate_client` & `process_url`.
Ξεκινώντας από το τέλος, η συνάρτηση `generate_client`, τύπου ασύγχρονης γεννήτριας, δημιουργεί έναν ασύχρονο http client, χρησιμοποιώντας τις βιβλιοθήκες httpx και contextlib (standard library), ενώ έχει και την αρμοδιότητα διαχείρισης τυχών http λαθών.

```py title="src/lib.py" linenums="1"
@asynccontextmanager
async def generate_client(
    base_url: Optional[str] = "",
) -> AsyncGenerator[AsyncClient, None]:
    """Configure an async http client for the crawler to use"""
    headers = {
        "User-Agent": "MapMakingCrawler/x.y.z",
        "Accept": "text/html,application/json,application/xml;q=0.9",
        "Keep-Alive": "500",
        "Connection": "keep-alive",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en, el-GR;q=0.9",
    }
    transport = AsyncHTTPTransport(retries=3, http2=True)
    client = AsyncClient(
        base_url=base_url,
        transport=transport,
        headers=headers,
        follow_redirects=True,
        default_encoding=lambda content: chardet.detect(content).get("encoding"),
    )
    try:
        yield client
    except RequestError as e:
        logger.error(e)
    finally:
        await client.aclose()
```
Από πάνω προς τα κάτω, ξεκινάμε ορίζοντας τη μέθοδο με τον decorator `@asynccontextmanager` ώστε να μπορεί να χρησιμοποιηθεί με το keyword `async with` μέσα σε άλλα μπλοκ κώδικα.

Η παράμετρος `base_url` είναι προαιρετική και θέτει ένα σταθερό string στον http client που συνήθως είναι το domain name του site στόχου.

Στη συνέχεια υπάρχει μια λίστα με headers που πρέπει να υπάρχουν ώστε να απαντήσει σωστά ο web server του site στόχου. Τα headers `Keep-Alive` & `Connection` απορρίπτονται όταν χρησιμοποιείται πρωτόκολο http/2, όπως θα δούμε αργότερα. Για την υποστήριξη του brotli αλγορίθμου συμπίεσης, όπως φαίνεται στο header `Accept-Encoding` χρειάστηκε η εγκατάσταση του πακέτου [brotli](https://github.com/google/brotli).

Αργότερα ορίζεται ένα [HTTPTransport Layer](https://www.python-httpx.org/advanced/transports/) ώστε να ενσωματωθεί η δυνατότητα επανάληψης ανεπιτυχών requests, αλλά και υποστήριξη http/2 προτοκόλου, μέσω της βιβλιοθήκης [h2](https://python-hyper.org/projects/hyper-h2/en/stable/). Το προτόκολο http/2 χρησιμοποιείται ώστε να μη ξεχωρίζει τόσο πολύ η αράχνη από κοινούς επισκέπτες του site στόχου. Θεωρητικά, δε θα πρέπει να υπάρχει κάποιο κέρδος στην απόδοση, μιας και δεν αξιοποιείται κάπου η [δυνατότητα αποστολής συγκεντροτικών TCP συνδέσεων](https://www.akamai.com/blog/performance/improve-ux-with-http2-multiplexed-requests). 

Ο http client παίρνει, πέρα του `base_url` `headers` και `transport`, τις παραμέτρους `follow_redirects` και `default_encoding`. Το `follow_redirects` προορίζεται για τις 3XX responses, ενώ το `default_encoding` για τη κωδικοποίηση του περιεχομένου εντός του html αρχείου. Αυτό γίνεται αυτόματα με τη χρήση του πακέτου [chardet](https://github.com/chardet/chardet).

Τέλος η συνάρτηση επιστρέφει μέσω yield τον http client, ενώ φροντίζει να κλείσει τη διεργασία με το keyword `finally`. 

Από τη μεριά της, η συνάρτηση process_url αναλαμβάνει τη δημιουργία και την εκτέλεση μιας παραμετροποιημένης εκδοχής της αράχνης, μαζί με ττα dependencies της. Υπεύθυνος για την κλήση της συνάρτησης αυτής είναι ο processor.

```py title="src/lib.py" linenums="1"
async def process_url(
    url: str,
    compressor: Compressor,
    crawl_depth: CrawlDepth,
    request_limit: ConcurrentRequestLimit,
) -> None:
    """Function to run from the task queue to process a url and compress the graph
    Contains all necessary steps to crawl a website and save a graph to disk in a
    compressed format
    :param url: base url to crawl
    :param compressor: compressor module to use
    :return: Future (in separate thread)
    """
    compressor_module = import_module(compressor.value)
    async with generate_client(url) as client:
        crawler = Crawler(
            client=client,
            max_depth=crawl_depth.value,
            semaphore_size=request_limit.value,
        )
        await crawler.parse_robotsfile()
        logger.info("Crawling Website")
        await crawler.build_graph(url)
        logger.info("Compressing Graph")
        await crawler.compress_graph(
            urlparse(url).netloc,
            compressor_module,
            compressor_extensions[compressor],
        )
```
Ως ορίσματα δέχετε το url στόχο, μία enum μεταβλητή τύπου Compressor, το επιθυμητό εύρος διερεύνησης και το ρυθμό που αποστέλονται τα requests. 

Το πρώτο που πρέπει να γίνει είναι ένα δυναμικό `import` με τη χρήση της `importlib`, που είναι μέρος της standard βιβλιοθήκης. Το import βασίζεται στην τιμή της enum μεταβλητής, που αντιστοιχεί στο όνομα ενός module αλγορίθμου συμπίεσης, πχ `gzip`.

Ακολουθεί η δημιουργία http client, όπως και τα βήματα εκτέλεσης της διερεύνησης, δηλαδή η επεξεργασία του robots αρχείου, η διερεύνηση καθ'αυτή και η τελική συμπίεση. Σημασία εδώ έχει η επεξερασία του url εισόδου με τη συνάρτηση `urlparse`, μέρος του builtin module `urllib.parse` ώστε να εξασφαλιστεί η σωστή δομή του url. Αντίστοιχα, ενδιαφέρον έχουν η παράμετρος `compressor_module` τύπου ModuleType και η σταθερά compressor_extensions[compressor] που αντιστοιχεί στη κατάλληξη του συμπιεσμένου αρχείου ανάλογα με το αλγόριθμο συμπίεσης που θα χρησιμοποιηθεί.

Η κλάση της αράχνης υλοποιείται κάπως έτσι.

```py title="src/lib.py" linenums="1"
class Crawler:
    def __init__(
        self, client: AsyncClient, max_depth: int = 5, semaphore_size: int = 50
    ) -> None:
        self.client: AsyncClient = client
        self.max_depth: int = max_depth
        self.semaphore_size: int = semaphore_size
        self.robotparser: Optional[RobotFileParser] = None
        self.graph: nx.Graph = nx.Graph()
        self.exclusion_list: List[str] = [".pdf", ".xml", ".jpg", ".png"]

    async def parse_robotsfile(self) -> None:
        """Create a parser instance to check against while crawling"""
        robotparser = RobotFileParser()
        rbfile = await self.client.get("/robots.txt")
        robotparser.parse(rbfile.text.split("\n") if rbfile.status_code == 200 else "")
        self.robotparser = robotparser

    async def check_robots_compliance(self, url: str) -> bool:
        """Check if url is allowed by robots.txt
        :param url: url to check
        :return: bool
        """
        return self.robotparser.can_fetch("*", url)

    async def pre_crawl_setup(self, start_url: str) -> bool:
        """Returns a ready for crawl flag
        The result can be false, not ready for crawl, if the website returns an error
        http status code.
        Otherwise moodify the headers of the client pool if its perfoming the upcoming
        requests over http/2
        """
        test_connection_response = await self.client.head(start_url)

        try:
            test_connection_response.raise_for_status()
        except HTTPStatusError:
            logger.info("Crawling not permitted on this website")
            return False

        if test_connection_response.extensions["http_version"] == b"HTTP/2":
            del self.client.headers["Keep-Alive"]
            del self.client.headers["Connection"]
            logger.info("Set up headers for http/2")

        logger.info(
            f"Crawling initialized from client @ {test_connection_response.extensions["network_stream"].get_extra_info("server_addr")}"
        )
        return True

    def check_against_exclusion_list(self, path: str) -> bool:
        """Return True if the path matches a pattern inside the crawler's exclusion list"""
        for item in self.exclusion_list:
            if item in path:
                return True
        return False

    async def build_graph(self, start_url: str) -> None:
        """Function to run from the task queue to process a url and compress the graph
        :param start_url: url to start from
        """
        visited = set()
        semaphore = asyncio.Semaphore(self.semaphore_size)

        if not await self.pre_crawl_setup(start_url):
            return

        anchor_selector = CSSSelector("a[href]")

        async def crawl(
            crawler: Crawler,
            url: str,
            depth: int,
        ) -> None:
            """Recursive function to crawl a website and build a graph
            :param depth: depth of recursion; how many calls shall be allowed
            """
            if depth > crawler.max_depth or url in visited:
                return

            p = urlparse(url, allow_fragments=False).path
            logger.info(f"Crawling: {p}")
            visited.add(url)
            crawler.graph.add_node(url)
            
            if self.check_against_exclusion_list(p):
                return

            try:
                async with semaphore:
                    response = await crawler.client.get(url)
                if response.status_code != 200:
                    logger.info(f"Non-200 response: {p}")
                    return
                if "text/html" not in response.headers["Content-Type"]:
                    logger.info(f"Not HTML: {p}")
                    return
                if not await crawler.check_robots_compliance(url):
                    logger.info(f"Blocked by robots.txt: {p}")
                    return
                try:
                    tree = html.document_fromstring(response.text)
                except ParseError as e:
                    logger.error(e)
                    return

                for href in anchor_selector(tree):
                    full_url = urljoin(url, href.attrib["href"], allow_fragments=False)
                    next_url = urlparse(full_url, allow_fragments=False)
                    if "cdn-cgi" in next_url.path:
                        return
                    if next_url.netloc == urlparse(start_url).netloc:
                        crawler.graph.add_edge(url, full_url)
                        await crawl(crawler, full_url, depth + 1)

            except RequestError as e:
                logger.error(e)

        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(crawl(self, start_url, 0))
        except* ValueError as IPErrorGroup:
            logger.error(
                "Terminating due to error",
                *[str(e)[:100] for e in IPErrorGroup.exceptions],
            )
        except* KeyError as HeaderMissingErrorGroup:
            logger.error(
                "Terminating due to error",
                *[str(e)[:50] for e in HeaderMissingErrorGroup.exceptions],
            )
        except* ParseError as ParserErrorGroup:
            logger.error(
                "Terminating due to error",
                *[str(e)[:100] for e in ParserErrorGroup.exceptions],
            )
        return

    async def compress_graph(
        self,
        file_name: str,
        compressor_module: ModuleType,
        extension: str,
    ) -> None:
        """Save graph to disk in compressed format"""
        if self.graph.number_of_nodes() <= 1:
            logger.info("Skipping compression, no graph nodes found")
            return
        file_name = (GRAPH_ROOT / file_name).as_posix()
        data = nx.node_link_data(self.graph, edges="edges")
        with compressor_module.open(file_name + extension, "wb") as f:
            f.write(orjson.dumps(data))
```

### Σημειώσεις: Αράχνη
#### Εξερεύνηση
    
περιγραφή

#### DNS Caching & Transport Layer

περιγραφή

### Στρατηγική Δημιουργίας Εργασιών 

### Υλοποίηση Δημιουργίας Εργασιών

### Σημειώσεις: Εργασίες Αράχνης
#### Παρακολούθηση Ουράς

περιγραφή

## Μετρικές Απόδοσης

* Ποσοστό σελίδων που βρέθηκαν
* Peak & baseline χρήση μνήμης σε αναλογία με το μέγεθος του γράφου
* Peak & baseline χρήση επεξεργαστή σε αναλογία με το μέγεθος του γράφου

## Πηγές

* [HTTP/2 For Web Developers - Cloudflare](https://blog.cloudflare.com/http-2-for-web-developers/)
* [Improve User Experience with Parallel Execution of HTTP/2 Multiplexed Requests - Akamai](https://www.akamai.com/blog/performance/improve-ux-with-http2-multiplexed-requests)