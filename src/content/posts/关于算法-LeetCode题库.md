---
title: 关于算法-LeetCode题库
published: 2017-09-11
description: "关于算法-面试常见的算法问题"
tags: []
category: 基础知识
draft: false
---

关于算法-面试常见的算法问题

## 三数之和

https://leetcode.cn/problems/3sum/

https://leetcode.cn/problems/3sum-closest/submissions/496369065/

策略：双指针

输入：一个数组

输出：返回所有和为0且不重复的三元组

```c#
public class Solution
{
	public IList<IList<int>> ThreeSum(int[] nums)
	{
		var result = new List<IList<int>>();
		int len = nums.Length;
		if (len < 3)
		{
			return result;
		}
		
		Array.Sort(nums);
		for(int i = 0; i< len-2; i++)
		{
			int left = i+1;
			int right = len-1;
			while(left < right)
			{
            	if(nums[i] + nums[left] + nums[right] == 0)
				{
					result.Add(new List<int>(){nums[i], nums[left], nums[right]});
					if(left < right && nums[left] == nums[left+1]) left++;
					if(left < right && nums[right] == nums[right-1]) right--;
				}
				left++;
				right--;
			}
		}
		
		return result;
	}
}
```

```
public class Solution {
    public IList<IList<int>> ThreeSum(int[] nums) {
        var result = new List<IList<int>>();
        int len = nums.Length;
        if(len < 3)
        {
            return result;
        }

        Array.Sort(nums);
        for(int i = 0; i < nums.Length-2; i++)
        {
            if(nums[i] > 0) break;
            if(i>0 && nums[i] == nums[i-1]) continue;
            int left = i+1;
            int right = len-1;
            while(left < right)
            {
                int sum = nums[i] + nums[left] + nums[right];
                if(sum == 0)
                {
                    result.Add(new List<int>(){nums[i], nums[left], nums[right]});
                    while(left < right && nums[left] == nums[left+1]) left++;
                    while(left<right && nums[left] == nums[right-1]) right--;
                    left++;
                    right--;
                }
                else if(sum < 0) left++;
                else if (sum > 0) right--;
            }
        }

        return result;
    }
}
```

