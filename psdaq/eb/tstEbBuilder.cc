#include "psdaq/eb/BatchManager.hh"
#include "psdaq/eb/EventBuilder.hh"
#include "psdaq/eb/EbEvent.hh"
#include "psdaq/eb/EbContribution.hh"
#include "psdaq/eb/Endpoint.hh"

#include "psdaq/eb/EbFtServer.hh"
#include "psdaq/eb/EbFtClient.hh"

#include "psdaq/service/Routine.hh"
#include "psdaq/service/Task.hh"
#include "psdaq/service/GenericPoolW.hh"
#include "xtcdata/xtc/Dgram.hh"

#include <unistd.h>
#include <stdio.h>
#include <time.h>
#include <signal.h>
#include <stdlib.h>
#include <inttypes.h>

using namespace XtcData;
using namespace Pds;
using namespace Pds::Fabrics;


static const uint64_t batch_duration   = 0x00000000000080UL; // ~128 uS; must be power of 2
static const unsigned max_batches      = 16; //8192;     // 1 second's worth
static const unsigned max_entries      = 128;     // 128 uS worth
static const size_t   header_size      = sizeof(Dgram);
static const size_t   input_extent     = 5; // Revisit: Number of "L3" input  data words
//static const size_t   result_extent    = 2; // Revisit: Number of "L3" result data words
static const size_t   result_extent    = input_extent;
static const size_t   max_contrib_size = header_size + input_extent  * sizeof(uint32_t);
static const size_t   max_result_size  = header_size + result_extent * sizeof(uint32_t);

static       bool     lverbose         = false;

//static void dump(const Pds::Dgram* dg)
//{
//  char buff[128];
//  time_t t = dg->seq.clock().seconds();
//  strftime(buff,128,"%H:%M:%S",localtime(&t));
//  printf("%s.%09u %016lx %s extent 0x%x ctns %s damage %x\n",
//         buff,
//         dg->seq.clock().nanoseconds(),
//         dg->seq.stamp().pulseID(),
//         Pds::TransitionId::name(dg->seq.service()),
//         dg->xtc.extent,
//         Pds::TypeId::name(dg->xtc.contains.id()),
//         dg->xtc.damage.value());
//}

namespace Pds {
  namespace Eb {
    class TstEbInlet;

    class TheSrc : public Src
    {
    public:
      TheSrc(Level::Type level, unsigned id) :
        Src(level)
      {
        _log |= id;
      }
    };

    class Result : public Dgram
    {
    public:
      Result(const Dgram& dg, Src& src) :
        Dgram(dg),
        _dst(_dest),
        _idx(_index)
      {
        xtc.src = src;
      }
    public:
      PoolDeclare;
    public:
      void destination(unsigned dst, unsigned idx)
      {
        *_dst++ = dst;
        *_idx++ = idx;
      }
    public:
      size_t   nDsts()         const { return _dst - _dest; }
      unsigned dst(unsigned i) const { return _dest[i];     }
      unsigned idx(unsigned i) const { return _index[i];    }
    private:
      uint32_t  _payload[result_extent]; // Revisit: buffer
    private:
      unsigned* _dst;
      unsigned* _idx;
    private:
#define NDST  64                        // Revisit: NDST
      unsigned  _dest[NDST];
      unsigned  _index[NDST];
    };

    class TstEbOutlet : public BatchManager,
                        public Routine
    {
    public:
      TstEbOutlet(EbFtBase& outlet,
                  unsigned  id,
                  uint64_t  duration,
                  unsigned  maxBatches,
                  unsigned  maxEntries,
                  size_t    maxSize);
      ~TstEbOutlet() { }
    public:
      void start(TstEbInlet& inlet);
      void shutdown()
      {
        _running = false;

        _task->destroy();
      }
    public:
      void post(Result*);
    public:                             // Routine interface
      void routine();
      void post(Batch* batch);
    private:
      Batch* _pend();
      void _release(Batch*);
    private:
      EbFtBase&     _outlet;
      unsigned      _maxBatches;
      unsigned      _maxEntries;
      volatile bool _running;
      Task*         _task;
      Semaphore     _resultSem;
      Queue<Batch>  _pending;
    };

    class TstEbInlet : public EventBuilder
    {
    public:
      TstEbInlet(EbFtBase&    inlet,
                 unsigned     id,
                 uint64_t     duration,
                 unsigned     maxBatches,
                 unsigned     maxEntries,
                 uint64_t     contributors,
                 TstEbOutlet& outlet);
    virtual   ~TstEbInlet() { }
    public:
      void     shutdown()  { _running = false; }
    public:
      void     process();
    public:
      void*    resultsPool() const;
      size_t   resultsPoolSize() const;
      void     process(EbEvent* event);
      uint64_t contract(const Dgram* contrib) const;
      void     fixup(EbEvent* event, unsigned srcId);
    private:
      Result* _allocate(EbEvent* event);
    private:
      EbFtBase&     _inlet;
      Src           _src;
      const TypeId  _tag;
      uint64_t      _contract;
      GenericPoolW  _results;
      //EbDummyTC     _dummy;           // Template for TC of dummy contributions  // Revisit: ???
      TstEbOutlet&  _outlet;
      volatile bool _running;
    };

  };
};


using namespace Pds::Eb;

TstEbInlet::TstEbInlet(EbFtBase&    inlet,
                       unsigned     id,
                       uint64_t     duration,
                       unsigned     maxBatches,
                       unsigned     maxEntries,
                       uint64_t     contributors,
                       TstEbOutlet& outlet) :
  EventBuilder(maxBatches, maxEntries, __builtin_popcountll(contributors), duration),
  _inlet(inlet),
  _src(TheSrc(Level::Event, id)),
  _tag(TypeId::Data, 0), //_l3SummaryType),
  _contract(contributors),
  _results(sizeof(Result), maxEntries),
  //_dummy(Level::Fragment),
  _outlet(outlet),
  _running(true)
{
  start();                              // Start the event timeout timer
}

void* TstEbInlet::resultsPool() const
{
  return _results.buffer();
}

size_t TstEbInlet::resultsPoolSize() const
{
  return _results.size();
}

void TstEbInlet::process()
{
  while (_running)
  {
    // Pend for an input datagram (batch) and pass its datagrams to the event builder.
    const Dgram* batch = (const Dgram*)_inlet.pend();
    if (!batch)  break;

    unsigned index = (batch->xtc.src.log() >> 8) & 0xffff;

    if (lverbose)
    {
      static unsigned cnt = 0;
      printf("EbInlet  rcvd  %6d        batch[%2d] @ %p, ts %014lx, sz %zd\n", ++cnt, index,
             batch, batch->seq.stamp().pulseId(), sizeof(*batch) + batch->xtc.sizeofPayload());
    }

    const Dgram* entry = (const Dgram*)batch->xtc.payload();
    const Dgram* end   = (const Dgram*)batch->xtc.next();
    while(entry != end)
    {
      //printf("EbInlet found a contrib %p, ts %014lx, sz %zd\n",
      //       entry, entry->seq.stamp().pulseId(), sizeof(*entry) + entry->xtc.sizeofPayload());

      EventBuilder::process(entry, index);

      entry = (const Dgram*)entry->xtc.next();
    }
  }
}

void TstEbInlet::process(EbEvent* event)
{
  //printf("Event ts %014lx, contract %016lx, size = %zd\n",
  //       event->sequence(), event->contract(), event->size());
  //event->dump(-1);

  //const unsigned recThresh = 10;       // Revisit: Some crud for now
  //const unsigned monThresh = 5;        // Revisit: Some crud for now

  Result* result = _allocate(event);

  // Iterate over the event and build a result datagram
  EbContribution* contrib = event->creator();
  EbContribution* end     = event->empty();
  //unsigned        sum     = 0;
  uint32_t*       buffer  = (uint32_t*)result->xtc.alloc(result_extent * sizeof(uint32_t));
  memset(buffer, 0, result_extent * sizeof(uint32_t));
  do
  {
    // The source of the contribution is one of the dsts
    result->destination(contrib->number(), contrib->data());

    const Dgram* idg     = contrib->datagram();
    uint32_t*    payload = (uint32_t*)idg->xtc.payload();
    size_t       length  = idg->xtc.sizeofPayload() / sizeof(*payload);

    //printf("TstEbInlet        result %p, contrib %p, ts %014lx, dst %2d, idx %2ld, pyld %08x %08x %08x %08x %08x\n",
    //       result, contrib, contrib->datagram()->seq.stamp().pulseId(), contrib->number(), contrib->data(),
    //       payload[0], payload[1], payload[2], payload[3], payload[4]);

    for (unsigned i = 0; i < length; ++i)
    {
      buffer[i] |= payload[i];          // Revisit: Some crud for now
    }
  }
  while ((contrib = contrib->forward()) != end);

  //buffer[0] = sum > recThresh ? 0 : 1; // Revisit: Some crud for now
  //buffer[1] = sum > monThresh ? 0 : 1; // Revisit: Some crud for now

  _outlet.post(result);
}

uint64_t TstEbInlet::contract(const Dgram* contrib) const
{
  // Determine the read-out group to which contrib belongs
  // Look up the expected list of contributors -> contract

  return _contract;
}

void TstEbInlet::fixup(EbEvent* event, unsigned srcId)
{
  // Revisit: Nothing can usefully be done here since there is no way to
  //          know the buffer index to be used for the result, I think

  if (lverbose)
  {
    fprintf(stderr, "%s: Called for source %d\n", __PRETTY_FUNCTION__, srcId);
  }

  // Revisit: What can be done here?
  //          And do we want to send a result to a contributor we haven't heard from?
  //Datagram* datagram = (Datagram*)event->data();
  //Damage    dropped(1 << Damage::DroppedContribution);
  //Src       source(srcId, 0);
  //
  //datagram->xtc.damage.increase(Damage::DroppedContribution);
  //
  //new(&datagram->xtc.tag) Xtc(_dummy, source, dropped); // Revisit: No tag, no TC
}

Result* TstEbInlet::_allocate(EbEvent* event)
{
  EbContribution* contrib = event->creator();
  const Dgram*    idg     = contrib->datagram();

  // Due to the resource-wait memory allocator used here, zero is never returned
  Result* result = new(&_results) Result(*idg, _src);

  return result;
}

TstEbOutlet::TstEbOutlet(EbFtBase& outlet,
                         unsigned  id,
                         uint64_t  duration,
                         unsigned  maxBatches,
                         unsigned  maxEntries,
                         size_t    maxSize) :
  BatchManager(TheSrc(Level::Event, id), duration, maxBatches, maxEntries, maxSize),
  _outlet(outlet),
  _maxBatches(maxBatches),
  _maxEntries(maxEntries),
  _running(true),
  _task (new Task(TaskObject("tOutlet"))),
  _resultSem(Semaphore::EMPTY),
  _pending()
{
}

void TstEbOutlet::start(TstEbInlet& inlet)
{
  MemoryRegion* mr[2];

  mr[0] = _outlet.registerMemory(batchPool(),         batchPoolSize());
  mr[1] = _outlet.registerMemory(inlet.resultsPool(), inlet.resultsPoolSize());

  BatchManager::start(_maxBatches, _maxEntries, mr);

  _task->call(this);
}

Batch* TstEbOutlet::_pend()
{
  _resultSem.take();
  Batch* batch = _pending.remove();

  if (lverbose)
  {
    const Dgram* bdg = batch->datagram();
    printf("TstEbOutlet read  batch[%d] %p, dg %p (ts %014lx, ext %zd)\n",
           batch->index(), batch, bdg, bdg->seq.stamp().pulseId(), sizeof(*bdg) + bdg->xtc.sizeofPayload());
  }

  return batch;
}

void TstEbOutlet::routine()
{
  static unsigned cnt = 0;

  while (_running)
  {
    // Pend for a result batch (datagram).  When it arrives, post it to all
    // contributors to the batch.
    // This could be done in the same thread as the that of the EB but isn't
    // so that the event builder can make progress building events from input
    // contributions while the back end is stalled behind the transport waiting
    // for resources to transmit the batch.

    Batch* batch = _pend();

    ++cnt;

    LocalIOVec&         pool = batch->pool();
    const struct iovec* iov  = pool.iovecs();

    // Revisit: Here we assume the first Result represents all results in the batch
    //          and send the batch to the destinations and indices given therein.
    //          Really need to get the set of destinations and indicies from ALL the
    //          Results in the Batch, in case there are multiple readout groups.

    Result*      result = (Result*)iov[1].iov_base; // First IOV is the Batch datagram
    unsigned     nDsts  = result->nDsts();
    const Dgram* bdg    = batch->datagram(); // Better equal &iov[0]->iov_base!
    size_t       extent = batch->extent();

    for (unsigned dst = 0; dst < nDsts; ++dst)
    {
      unsigned dest   = result->dst(dst);
      unsigned idx    = result->idx(dst);

      if (lverbose)
      {
        void*    rmtAdx = (void*)_outlet.rmtAdx(dest, idx * maxBatchSize());
        printf("EbOutlet posts       %6d result[%2d] @ %p, ts %014lx, sz %zd to Contrib %d %p\n", cnt,
               idx, bdg, bdg->seq.stamp().pulseId(), extent, dest, rmtAdx);
      }

      _outlet.post(pool, extent, dest, idx * maxBatchSize(), NULL);
    }

    _release(batch);
  }
}

void TstEbOutlet::post(Result* result)
{
  // Accumulate output datagrams (result) from the event builder into a batch
  // datagram.  When the batch completes, post it to the back end.

  if (lverbose)
  {
    printf("TstEbOutlet posts result[%d] %p (ts %014lx, ext %zd)\n",
           result->idx(0), result, result->seq.stamp().pulseId(), sizeof(*result) + result->xtc.sizeofPayload());
  }

  process(result);
}

void TstEbOutlet::post(Batch* batch)
{
  _pending.insert(batch);
  _resultSem.give();
}

void TstEbOutlet::_release(Batch* batch)
{
  LocalIOVec&         pool = batch->pool();
  const struct iovec* iov  = pool.iovecs();
  const struct iovec* end  = &iov[pool.count()];

  ++iov;                                // First one is the Batch datagram

  for (; iov < end; ++iov)
  {
    delete (Result*)iov->iov_base;
  }

  delete batch;
}


static TstEbInlet* ebInlet  = NULL;

void sigHandler( int signal )
{
  static unsigned callCount = 0;

  printf("sigHandler() called\n");

  if (ebInlet)  ebInlet->shutdown();

  if (callCount++)  ::abort();
}

void usage(char *name, char *desc)
{
  fprintf(stderr, "Usage:\n");
  fprintf(stderr, "  %s [OPTIONS] <contributor_addr> [<contributor_addr> [...]]\n", name);

  if (desc)
    fprintf(stderr, "\n%s\n", desc);

  fprintf(stderr, "\nOptions:\n");

  fprintf(stderr, " %-20s %s\n", "-B <srv_port>",
          "Builder's port number (server: 32768)");
  fprintf(stderr, " %-20s %s\n", "-P <clt_port>",
          "Contributor port number (client: 32769)");

  fprintf(stderr, " %-20s %s\n", "-i <ID>",
          "Unique ID this instance should assume (0 - 63) (default: 0)");

  fprintf(stderr, " %-20s %s\n", "-h", "display this help output");
  fprintf(stderr, " %-20s %s\n", "-v", "enable debugging output");
}

int main(int argc, char **argv)
{
  int op, ret = 0;
  unsigned id = 0;
  std::string srv_port("32768");        // Port served to contributors
  std::string clt_port("32769");        // Port served by contributors
  std::vector<std::string> clt_addr;

  while ((op = getopt(argc, argv, "hvB:P:i:")) != -1)
  {
    switch (op)
    {
      case 'B':  srv_port = std::string(optarg);  break;
      case 'P':  clt_port = std::string(optarg);  break;
      case 'i':  id       = atoi(optarg);         break;
      case 'v':  lverbose = true;                 break;
      case '?':
      case 'h':
      default:
        usage(argv[0], (char*)"Test event builder");
        return 1;
    }
  }

  uint64_t clients = 0;
  unsigned srcId   = 0;
  if (optind < argc)
  {
    do
    {
      clt_addr.push_back(std::string(argv[optind]));
      clients |= 1 << srcId++;          // Revisit srcId value
    }
    while (++optind < argc);
  }
  else
  {
    fprintf(stderr, "Contributor address(s) is required\n");
    return 1;
  }

  ::signal( SIGINT, sigHandler );

  printf("Parameters:\n");
  printf("  Batch duration:             %014lx = %ld uS\n", batch_duration, batch_duration);
  printf("  Batch pool depth:           %d\n", max_batches);
  printf("  Max # of entries per batch: %d\n", max_entries);
  printf("  Max contribution size:      %zd\n", max_contrib_size);
  printf("  Max result       size:      %zd\n", max_result_size);

  unsigned numContribs = clt_addr.size();
  size_t   contribSize = max_batches * (sizeof(Dgram) + max_entries * max_contrib_size);
  size_t   resultSize  = max_batches * (sizeof(Dgram) + max_entries * max_result_size);

  EbFtServer fts(srv_port, numContribs, contribSize);
  ret = fts.connect();
  if (ret)
  {
    fprintf(stderr, "FtServer connect() failed\n");
    return ret;
  }

  EbFtClient ftc(clt_addr, clt_port, resultSize);
  unsigned   tmo(120);                  // Seconds
  ret = ftc.connect(tmo);
  if (ret)
  {
    fprintf(stderr, "FtClient connect() failed\n");
    return ret;
  }

  TstEbOutlet outlet(ftc, id, batch_duration, max_batches, max_entries, max_result_size);
  TstEbInlet  inlet (fts, id, batch_duration, max_batches, max_entries, clients, outlet);
  ebInlet = &inlet;

  outlet.start(inlet);

  inlet.process();

  outlet.shutdown();
  ftc.shutdown();
  fts.shutdown();

  return ret;
}
