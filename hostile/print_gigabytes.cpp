#include <cstdio>
#include <cstring>

int main() {
    static char line[1024 * 1024];
    std::memset(line, 'x', sizeof(line));
    while (true) std::fwrite(line, 1, sizeof(line), stdout);
}
