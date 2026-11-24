import heapq
from collections import defaultdict


def merge(word, pair):
    new = []
    i = 0

    while i < len(word):
        if i < len(word) - 1 and word[i] == pair[0] and word[i+1] == pair[1]:
            new.append(word[i] + word[i+1])
            i += 2
        else:
            new.append(word[i])
            i += 1

    return new


def train(corpus, num_merges):
    
    words = [tuple(w) for w, _ in corpus]
    freqs = [f for _, f in corpus]

    counts = defaultdict(int)
    where = defaultdict(set)

    for i, word in enumerate(words):
        for p in zip(word, word[1:]):
            counts[p] += freqs[i]
            where[p].add(i)
    

    heap = [(-c, p) for p, c in counts.items()] # Using min-heap to get most frequent pair but negating the count so its on top
    heapq.heapify(heap) 

    merges =[]
    while heap and len(merges) < num_merges:
        neg_count, best_pair = heapq.heappop(heap)
        # Lazy deletion, skip if count has changed since pushed
        if counts.get(best_pair, 0) != -neg_count:
            continue
        if -neg_count < 2:
            break
        merges.append(best_pair)

        delta = defaultdict(int)
        
        for i in where.pop(best_pair):
            old = words[i]
            new = merge(old, best_pair)
            if len(new) == len(old):
                continue
            
            f = freqs[i]
            words[i] = tuple(new)
            
            for p in zip(old, old[1:]):
                delta[p] -= f
                where[p].discard(i)
            
            for p in zip(new, new[1:]):
                delta[p] += f
                where[p].add(i)

        for p, d in delta.items():
            if d == 0:
                continue
            counts[p] += d
            if counts[p] > 0:
                heapq.heappush(heap, (-counts[p], p))
            else:
                del counts[p] 

    return merges

def encode(word, merges):
    token = list(word)
    
    for pair in merges:
        token = merge(token, pair)
    return token


if __name__ == "__main__":
    corpus = [("walk", 10), ("walked", 5), ("walking", 3), ("walks", 2), ("run", 8), ("ran", 4), ("running", 6), ("runs", 1)]
    merges = train(corpus, 5)
    print(f"merges: {merges}")
    print(f"encoded 'walking': {encode('walking', merges)}")
