#include <gtest/gtest.h>
#include <vector>

// Registration grows GoogleTest's private vector<int>. With a prebuilt static
// framework, unsanitized and instrumented STL template bodies could coalesce
// and disagree about which elements ASan had unpoisoned.
template<typename T>
class SdkRegistration : public ::testing::Test
{
};
using RegistrationTypes = ::testing::Types<int, unsigned, short, long, char, double>;
TYPED_TEST_SUITE(SdkRegistration, RegistrationTypes);

TYPED_TEST(SdkRegistration, instrumented_consumer)
{
  // Instantiate the same common STL helpers in the instrumented consumer.
  std::vector<int> values;
  for (int index = 0; index < 16; ++index)
    values.emplace_back(index + 1);
  EXPECT_EQ(values.back(), 16);
}
