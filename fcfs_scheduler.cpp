#include <algorithm>
#include <iostream>
#include <string>
#include <vector>

struct Job {
    long long id{};
    long long arrival{};
    long long service{};
    int priority{};
};

int main(int argc, char* argv[]) {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    const bool aging = argc > 1 && std::string(argv[1]) == "--aging";
    long long aging_interval = 5;
    if (argc > 2) {
        try {
            aging_interval = std::stoll(argv[2]);
        } catch (...) {
            std::cerr << "Invalid aging interval.\n";
            return 5;
        }
    }
    if (aging_interval <= 0) {
        std::cerr << "Aging interval must be positive.\n";
        return 5;
    }

    int n = 0;
    if (!(std::cin >> n) || n < 0 || n > 100000) {
        std::cerr << "Invalid job count.\n";
        return 2;
    }

    std::vector<Job> jobs;
    jobs.reserve(static_cast<std::size_t>(n));
    for (int i = 0; i < n; ++i) {
        Job job;
        if (!(std::cin >> job.id >> job.arrival >> job.service >> job.priority)) {
            std::cerr << "Invalid job input at row " << i + 1 << ".\n";
            return 3;
        }
        if (job.id <= 0 || job.arrival < 0 || job.service <= 0 || job.priority < 1 || job.priority > 4) {
            std::cerr << "Invalid job: ID must be positive, arrival non-negative, service positive, priority 1-4.\n";
            return 4;
        }
        jobs.push_back(job);
    }

    std::vector<bool> done(jobs.size(), false);
    long long clock = 0;
    long long order = 1;
    int completed = 0;

    while (completed < n) {
        int selected = -1;
        for (int i = 0; i < n; ++i) {
            if (done[i] || jobs[i].arrival > clock) continue;
            if (selected == -1) {
                selected = i;
                continue;
            }
            if (!aging) {
                if (jobs[i].arrival < jobs[selected].arrival ||
                    (jobs[i].arrival == jobs[selected].arrival && jobs[i].id < jobs[selected].id)) {
                    selected = i;
                }
            } else {
                const long long wait_i = clock - jobs[i].arrival;
                const long long wait_s = clock - jobs[selected].arrival;
                const int effective_i = static_cast<int>(std::max(1LL, jobs[i].priority - wait_i / aging_interval));
                const int effective_s = static_cast<int>(std::max(1LL, jobs[selected].priority - wait_s / aging_interval));
                if (effective_i < effective_s ||
                    (effective_i == effective_s && jobs[i].arrival < jobs[selected].arrival) ||
                    (effective_i == effective_s && jobs[i].arrival == jobs[selected].arrival && jobs[i].id < jobs[selected].id)) {
                    selected = i;
                }
            }
        }

        if (selected == -1) {
            long long next_arrival = -1;
            for (int i = 0; i < n; ++i) {
                if (!done[i] && (next_arrival == -1 || jobs[i].arrival < next_arrival)) {
                    next_arrival = jobs[i].arrival;
                }
            }
            clock = std::max(clock, next_arrival);
            continue;
        }

        const Job& job = jobs[selected];
        const long long start = std::max(clock, job.arrival);
        const long long completion = start + job.service;
        const long long waiting = start - job.arrival;
        const long long turnaround = completion - job.arrival;
        std::cout << job.id << ' ' << job.arrival << ' ' << job.service << ' '
                  << start << ' ' << completion << ' ' << waiting << ' '
                  << turnaround << ' ' << waiting << ' ' << order << '\n';
        clock = completion;
        done[selected] = true;
        ++completed;
        ++order;
    }
    return 0;
}
