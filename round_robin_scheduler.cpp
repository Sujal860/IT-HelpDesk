#include <algorithm>
#include <deque>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

struct Job {
    long long id;
    long long arrival;
    long long service;
    long long remaining;
    long long first_start = -1;
    long long completion = -1;
    long long waiting = 0;
    long long turnaround = 0;
    long long response = 0;
    long long order = 0;
};
struct Segment { long long id, start, end; };

int main(int argc, char** argv) {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);
    if (argc < 2) { std::cerr << "Usage: rr_scheduler quantum [context_switch_overhead]\n"; return 2; }
    long long quantum = 0, overhead = 0;
    try { quantum = std::stoll(argv[1]); if (argc > 2) overhead = std::stoll(argv[2]); }
    catch (...) { std::cerr << "Invalid scheduler parameter.\n"; return 2; }
    if (quantum <= 0 || overhead < 0 || quantum > 1000000 || overhead > 1000000) {
        std::cerr << "Quantum must be positive; context-switch overhead cannot be negative.\n"; return 2;
    }
    int n = 0;
    if (!(std::cin >> n) || n < 0 || n > 100000) { std::cerr << "Invalid job count.\n"; return 3; }
    std::vector<Job> jobs; jobs.reserve(static_cast<std::size_t>(n));
    for (int i=0;i<n;i++) {
        Job j{};
        if (!(std::cin >> j.id >> j.arrival >> j.service)) { std::cerr << "Invalid job input.\n"; return 4; }
        if (j.id <= 0 || j.arrival < 0 || j.service <= 0) { std::cerr << "ID and service must be positive; arrival cannot be negative.\n"; return 5; }
        j.remaining = j.service; jobs.push_back(j);
    }
    std::sort(jobs.begin(), jobs.end(), [](const Job& a, const Job& b) {
        return a.arrival == b.arrival ? a.id < b.id : a.arrival < b.arrival;
    });
    std::deque<int> ready;
    std::vector<Segment> segments;
    long long clock = 0, switches = 0, first_order = 0;
    int next = 0, completed = 0, previous = -1;
    while (completed < n) {
        while (next < n && jobs[next].arrival <= clock) ready.push_back(next++);
        if (ready.empty()) {
            if (next < n) { clock = std::max(clock, jobs[next].arrival); continue; }
            break;
        }
        int idx = ready.front(); ready.pop_front();
        Job& job = jobs[idx];
        if (previous != -1 && previous != idx) { switches++; clock += overhead; }
        if (job.first_start == -1) { job.first_start = clock; job.order = ++first_order; }
        const long long run = std::min(quantum, job.remaining);
        const long long start = clock;
        clock += run;
        job.remaining -= run;
        segments.push_back({job.id, start, clock});
        while (next < n && jobs[next].arrival <= clock) ready.push_back(next++);
        if (job.remaining > 0) ready.push_back(idx);
        else {
            job.completion = clock;
            job.turnaround = job.completion - job.arrival;
            job.waiting = job.turnaround - job.service;
            job.response = job.first_start - job.arrival;
            completed++;
        }
        previous = idx;
    }
    std::cout << "C " << switches << "\n";
    for (const auto& s : segments) std::cout << "S " << s.id << " " << s.start << " " << s.end << "\n";
    std::sort(jobs.begin(), jobs.end(), [](const Job& a, const Job& b) { return a.order < b.order; });
    for (const auto& j : jobs)
        std::cout << "R " << j.id << " " << j.arrival << " " << j.service << " " << j.first_start << " " << j.completion << " " << j.waiting << " " << j.turnaround << " " << j.response << " " << j.order << "\n";
    return 0;
}
