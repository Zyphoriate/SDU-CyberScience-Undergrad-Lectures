#include "ucos_ii.h"
#include "stm32f10x.h"
#include <stdio.h>
#include <stdlib.h>
#include <os_cpu.h>

static OS_STK task1_stk[TASK1_STK_SIZE];
static OS_STK task2_stk[TASK1_STK_SIZE];
static OS_STK task3_stk[TASK1_STK_SIZE];
static OS_STK task4_stk[TASK1_STK_SIZE];
static OS_STK task5_stk[TASK1_STK_SIZE];
void task1(void *p_arg);
void task2(void *p_arg);
void task3(void *p_arg);
void task4(void *p_arg);
void task5(void *p_arg);
void ASM_Switch_To_Unprivileged(void);
void syscall_print_str(char *);
void syscall_systick_init(void);
void syscall_OSTimeDly(uint32_t);
INT8U syscall_OSTaskCreate(void (*task)(void *p_arg), void *p_arg, OS_STK *ptos, INT8U prio);
INT8U  syscall_OSTaskDel (INT8U prio);
void systick_init(void);
void print_str(char *);

int main(void)
{
	OSInit();
	systick_init();
	OSTaskCreate(task1, (void *)0,
		&task1_stk[TASK1_STK_SIZE - 1], TASK1_PRIO);
	OSTaskCreate(task2, (void *)0,
		&task2_stk[TASK2_STK_SIZE - 1], TASK2_PRIO);
	OSTaskCreate(task3, (void *)0,
		&task3_stk[TASK3_STK_SIZE - 1], 9);
	OSTaskCreate(task4, (void *)0,
		&task4_stk[TASK3_STK_SIZE - 1], 11);
	OSTaskCreate(task5, (void *)0,
		&task5_stk[TASK3_STK_SIZE - 1], 22);
	ASM_Switch_To_Unprivileged();
	OSStart();
	return 0;
}
static void task1(void *p_arg)
{
	for (int i = 1; i < 1000; i++) {
		syscall_print_str("Hello from Task 1!\n");
	}

	syscall_OSTaskDel(OS_PRIO_SELF);
}

static void task2(void *p_arg)
{
	for (int i = 1; i < 1000; i++) {
		syscall_print_str("Hello from Task 2!\n");
	}

	syscall_OSTaskDel(OS_PRIO_SELF);
}

static void task3(void *p_arg)
{
	int i;
	for (;;)
	{
		for (i = 1; i < 10; i++)
			;
		syscall_print_str("Hello from Task 3!\n");
	}
}

static void task4(void *p_arg)
{
	int i;
	for (;;)
	{
		for (i = 1; i < 10; i++)
			;
		syscall_print_str("Hello from Task 4!\n");
	}
}

static void task5(void *p_arg)
{
	int i;
	for (;;)
	{
		for (i = 1; i < 10; i++)
			;
		syscall_print_str("Hello from Task 5!\n");
	}
}

/*END OF THE FILE*/
