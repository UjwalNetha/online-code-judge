#include <cmath>
#include <cstdio>

int main() {
    double r;
    if (std::scanf("%lf", &r) != 1) return 1;
    std::printf("%.6f\n", M_PI * r * r);
}
