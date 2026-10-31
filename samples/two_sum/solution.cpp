#include <iostream>
#include <unordered_map>

int main() {
    int n;
    long long target;
    std::cin >> n >> target;

    std::unordered_map<long long, int> seen;
    for (int position = 1; position <= n; position++) {
        long long value;
        std::cin >> value;
        auto found = seen.find(target - value);
        if (found != seen.end()) {
            std::cout << found->second << " " << position << "\n";
            return 0;
        }
        seen[value] = position;
    }
}
