import simpy
from sim_tools.distributions import Exponential, Lognormal
import pandas as pd
import numpy as np


class Patient:
    def __init__(self, p_id):
        self.id = p_id

        self.q_time_registration = pd.NA
        self.q_time_nurse = pd.NA
        self.q_time_specialist = pd.NA


class Param:
    def __init__(
        self,
        mean_patient_inter=5,
        mean_registration_time=3,
        sd_registration_time=0.5,
        mean_nurse_consult_time=6,
        sd_nurse_consult_time=1,
        mean_specialist_time=60,
        sd_specialist_time=5,
        num_receptionists=1,
        num_nurses=1,
        num_specialists=1,
        specialist_prob=0.3,
        sim_duration=120,
        num_replications=5,
    ):
        self.mean_patient_inter = mean_patient_inter
        self.mean_registration_time = mean_registration_time
        self.sd_registration_time = sd_registration_time
        self.mean_nurse_consult_time = mean_nurse_consult_time
        self.sd_nurse_consult_time = sd_nurse_consult_time
        self.mean_specialist_time = mean_specialist_time
        self.sd_specialist_time = sd_specialist_time
        self.num_receptionists = num_receptionists
        self.num_nurses = num_nurses
        self.num_specialists = num_specialists
        self.specialist_prob = specialist_prob
        self.sim_duration = sim_duration
        self.num_replications = num_replications


class Model:
    def __init__(self, param, replication_id):
        self.param = param
        self.replication_id = replication_id
        self.env = simpy.Environment()
        self.patient_counter = 0

        self.receptionist = simpy.Resource(
            self.env, capacity=self.param.num_receptionists
        )
        self.nurse = simpy.Resource(self.env, capacity=self.param.num_nurses)

        self.specialist = simpy.Resource(self.env, capacity=self.param.num_specialists)

        ss = np.random.SeedSequence(self.replication_id)
        seeds = ss.spawn(5)
        self.patient_inter_dist = Exponential(
            mean=self.param.mean_patient_inter, random_seed=seeds[0]
        )
        self.registration_time_dist = Lognormal(
            mean=self.param.mean_registration_time,
            stdev=self.param.sd_registration_time,
            random_seed=seeds[2],
        )
        self.nurse_consult_time_dist = Lognormal(
            mean=self.param.mean_nurse_consult_time,
            stdev=self.param.sd_nurse_consult_time,
            random_seed=seeds[1],
        )

        self.specialist_branch_prob_rng = np.random.default_rng(seeds[3])

        self.specialist_time_dist = Lognormal(
            mean=self.param.mean_specialist_time,
            stdev=self.param.sd_specialist_time,
            random_seed=seeds[4],
        )

        self.list_of_patients = []
        self.mean_q_time_registration = pd.NA
        self.sd_q_time_registration = pd.NA
        self.perc_90_q_time_registration = pd.NA
        self.mean_q_time_nurse = pd.NA
        self.sd_q_time_nurse = pd.NA
        self.perc_90_q_time_nurse = pd.NA
        self.mean_q_time_specialist = pd.NA
        self.sd_q_time_specialist = pd.NA
        self.perc_90_q_time_specialist = pd.NA

    def generator_patient_arrivals(self):
        while True:
            self.patient_counter += 1
            p = Patient(self.patient_counter)
            self.list_of_patients.append(p)
            self.env.process(self.attend_clinic(p))
            sampled_inter = self.patient_inter_dist.sample()
            yield self.env.timeout(sampled_inter)

    def attend_clinic(self, patient):
        start_q_registration = self.env.now

        with self.receptionist.request() as req:
            yield req
            end_q_registration = self.env.now
            patient.q_time_registration = end_q_registration - start_q_registration
            sampled_reg_act_time = self.registration_time_dist.sample()
            yield self.env.timeout(sampled_reg_act_time)

        start_q_nurse = self.env.now

        with self.nurse.request() as req:
            yield req
            end_q_nurse = self.env.now
            patient.q_time_nurse = end_q_nurse - start_q_nurse
            sampled_nurse_act_time = self.nurse_consult_time_dist.sample()
            yield self.env.timeout(sampled_nurse_act_time)

        if self.specialist_branch_prob_rng.random() < self.param.specialist_prob:
            start_q_specialist = self.env.now

            with self.specialist.request() as req:
                yield req
                end_q_specialist = self.env.now
                patient.q_time_specialist = end_q_specialist - start_q_specialist
                sampled_specialist_act_time = self.specialist_time_dist.sample()
                yield self.env.timeout(sampled_specialist_act_time)

    def run_model(self):
        self.env.process(self.generator_patient_arrivals())
        self.env.run(until=self.param.sim_duration)

    def convert_entity_list_to_dataframe(self, entity_list):
        entity_dateframe = pd.DataFrame(entity.__dict__ for entity in entity_list)

        return entity_dateframe

    def calculate_run_results(self, entity_dataframe):
        self.mean_q_time_registration = entity_dataframe["q_time_registration"].mean()
        self.sd_q_time_registration = entity_dataframe["q_time_registration"].std()
        self.perc_90_q_time_registration = entity_dataframe[
            "q_time_registration"
        ].quantile(0.9)

        self.mean_q_time_nurse = entity_dataframe["q_time_nurse"].mean()
        self.sd_q_time_nurse = entity_dataframe["q_time_nurse"].std()
        self.perc_90_q_time_nurse = entity_dataframe["q_time_nurse"].quantile(0.9)

        self.mean_q_time_specialist = entity_dataframe["q_time_specialist"].mean()
        self.sd_q_time_specialist = entity_dataframe["q_time_specialist"].std()
        self.perc_90_q_time_specialist = entity_dataframe["q_time_specialist"].quantile(
            0.9
        )


base_case_params = Param()
base_case_model = Model(base_case_params, replication_id=1)
base_case_model.run_model()

patient_df = base_case_model.convert_entity_list_to_dataframe(
    base_case_model.list_of_patients
)
base_case_model.calculate_run_results(patient_df)

print("BASE CASE SINGLE RUN RESULTS")
print("-----------------------")

print("Queuing Time for Registration")
print(f"Mean : {base_case_model.mean_q_time_registration:.2f} minutes")
print(f"SD : {base_case_model.sd_q_time_registration:.2f} minutes")
print(f"90th Perc : {base_case_model.perc_90_q_time_registration:.2f}", "minutes")
print()

print("Queuing Time for the Nurse")
print(f"Mean : {base_case_model.mean_q_time_nurse:.2f} minutes")
print(f"SD : {base_case_model.sd_q_time_nurse:.2f} minutes")
print(f"90th Perc : {base_case_model.perc_90_q_time_nurse:.2f} minutes")
print()


print("Queuing Time for the Specialist")
print(f"Mean : {base_case_model.mean_q_time_specialist:.2f} minutes")
print(f"SD : {base_case_model.sd_q_time_specialist:.2f} minutes")
print(f"90th Perc : {base_case_model.perc_90_q_time_specialist:.2f} ", "minutes")
print()
